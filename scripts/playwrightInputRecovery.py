"""Exercise input retry via browser-only WebSocket fixtures; never answer live requests.

Set CODING_AGENT_CONSOLE_TEST_URL and CODEX_WEB_PASSWORD for the running console.
"""
import json
import os

from playwright.sync_api import expect, sync_playwright


def main():
    url = os.environ.get('CODING_AGENT_CONSOLE_TEST_URL', 'http://127.0.0.1:3032/')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        sockets = []
        attempts = []
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def route(ws):
            server = ws.connect_to_server()
            sockets.append(ws)

            def receive(raw):
                event = json.loads(raw)
                if event.get('type') in ('agent:serverRequest', 'codex:serverRequest'):
                    return
                if event.get('type') == 'gateway:snapshot':
                    event['snapshot']['pendingServerRequests'] = []
                ws.send(json.dumps(event))

            def send(raw):
                event = json.loads(raw)
                if event.get('type') in ('agent:serverResponse', 'codex:serverResponse'):
                    assert str(event.get('serverRequestId', '')).startswith('fixture:')
                    attempts.append(event)
                    ok = len(attempts) % 2 == 0
                    ws.send(json.dumps({'type': 'reply', 'requestId': event['requestId'],
                                        'ok': ok, 'result': {}, 'error': 'Fixture transient failure'}))
                else:
                    # This test performs only bootstrap/read/heartbeat operations.
                    server.send(raw)

            server.on_message(receive)
            ws.on_message(send)

        page.route_web_socket('**/ws', route)
        page.goto(url, wait_until='networkidle')
        password = page.get_by_placeholder('Password or token')
        if password.count():
            password.fill(os.environ['CODEX_WEB_PASSWORD'])
            page.get_by_role('button', name='Sign in', exact=True).click()
        page.locator('.statusPill.online').wait_for(timeout=30000)
        page.wait_for_timeout(1500)

        def question(request_id):
            sockets[-1].send(json.dumps({'type': 'agent:serverRequest', 'provider': 'claude', 'request': {
                'id': request_id, 'method': 'item/tool/requestUserInput', 'params': {
                    'threadId': 'fixture-thread', 'questions': [{'id': 'choice', 'header': 'Retry test',
                    'question': 'Choose a test answer', 'isOther': True, 'options': [
                        {'label': 'First', 'description': 'Fixture answer'},
                        {'label': 'Second', 'description': 'Another answer'}]}]}}}))

        for index, width in enumerate((1440, 390)):
            page.set_viewport_size({'width': width, 'height': 900})
            if index == 0:
                question('fixture:question-0')
            dialog = page.locator('.userInputDialog')
            expect(dialog).to_be_visible()
            expect(dialog.get_by_role('button', name='Confirm', exact=True)).to_be_disabled()
            dialog.get_by_role('radio').first.check()
            dialog.get_by_role('button', name='Confirm', exact=True).click()
            expect(dialog.get_by_role('alert')).to_contain_text('Fixture transient failure')
            expect(dialog.get_by_role('radio').first).to_be_checked()
            if index == 0:
                question('fixture:question-1')
            dialog.get_by_role('button', name='Confirm', exact=True).click()
            if index == 0:
                expect(dialog.get_by_role('button', name='Confirm', exact=True)).to_be_disabled()
            else:
                expect(dialog).to_have_count(0)
            assert attempts[-1]['result']['answers']['choice']['answers'] == ['First']

        sockets[-1].send(json.dumps({'type': 'codex:serverRequest', 'request': {
            'id': 'fixture:approval', 'method': 'item/commandExecution/requestApproval',
            'params': {'threadId': 'fixture-thread', 'command': 'echo fixture'}}}))
        dialog = page.locator('.approvalDialog')
        dialog.get_by_role('button', name='Approve', exact=True).click()
        expect(dialog.get_by_role('alert')).to_contain_text('Fixture transient failure')
        dialog.get_by_role('button', name='Approve', exact=True).click()
        expect(dialog).to_have_count(0)
        assert not errors, errors
        print(json.dumps({'questionRetry': 'passed desktop/mobile', 'approvalRetry': 'passed',
                          'responsesIntercepted': len(attempts), 'pageErrors': errors}))
        browser.close()


if __name__ == '__main__':
    main()
