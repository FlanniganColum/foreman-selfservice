from conftest import login
def test_user_only_sees_authorised_server(client):
    login(client,"alice"); r=client.get("/chiklets/deploy-web-application"); assert r.status_code==200; assert b"demo01" in r.data; assert b"secret01" not in r.data
def test_user_cannot_open_approvals(client):
    login(client,"alice"); assert client.get("/approvals/").status_code==403
