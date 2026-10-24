import sys; sys.path.insert(0, "/app/tests")
from smoke_backend import get_user, bapi
email = sys.argv[1] if len(sys.argv) > 1 else "smoke+clerk_test@example.com"
u = get_user(email)
print(bapi("/sign_in_tokens", {"user_id": u["id"], "expires_in_seconds": 1800})["token"])
