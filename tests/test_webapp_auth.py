import time

import pytest

from app.webapp.auth import InitDataError, LinkSigner, parse_init_data
from tests.helpers import BOT_TOKEN, make_init_data


def test_valid_init_data() -> None:
    data = parse_init_data(make_init_data(42, "Иван"), BOT_TOKEN)
    assert data.user is not None
    assert (data.user.id, data.user.first_name) == (42, "Иван")


def test_signature_from_another_bot_is_rejected() -> None:
    with pytest.raises(InitDataError):
        parse_init_data(make_init_data(42, token="999:other"), BOT_TOKEN)


def test_tampered_user_is_rejected() -> None:
    forged = make_init_data(42).replace("%22id%22%3A+42", "%22id%22%3A+1")
    with pytest.raises(InitDataError):
        parse_init_data(forged, BOT_TOKEN)


def test_stale_init_data_is_rejected() -> None:
    two_days_ago = int(time.time()) - 2 * 86400
    with pytest.raises(InitDataError, match="expired"):
        parse_init_data(make_init_data(42, auth_date=two_days_ago), BOT_TOKEN)


def test_signed_links() -> None:
    signer = LinkSigner("secret")
    url = signer.sign("/app/attachments/7", now=1000)
    query = dict(part.split("=") for part in url.split("?")[1].split("&"))

    assert signer.verify("/app/attachments/7", int(query["exp"]), query["sig"], now=1000)
    assert not signer.verify("/app/attachments/8", int(query["exp"]), query["sig"], now=1000)
    assert not signer.verify("/app/attachments/7", int(query["exp"]), query["sig"], now=10**9)
