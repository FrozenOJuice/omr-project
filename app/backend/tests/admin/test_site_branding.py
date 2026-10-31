import pytest

pytestmark = pytest.mark.db

PNG_LOGO = b"\x89PNG\r\n\x1a\n" + b"test-logo"


async def test_site_branding_is_public_and_defaults_to_aperture(client):
    response = await client.get("/api/site-branding")

    assert response.status_code == 200
    assert response.json()["logo_url"] == "/ApertureLogoFull.svg"
    assert response.json()["is_custom_logo"] is False

    logo = await client.get("/api/site-branding/logo", follow_redirects=False)
    assert logo.status_code == 307
    assert logo.headers["location"] == "/ApertureLogoFull.svg"


async def test_only_admin_can_upload_site_logo(
    client,
    register_user,
    auth_headers,
):
    user = await register_user()

    response = await client.put(
        "/api/admin/site-branding/logo",
        files={"file": ("logo.png", PNG_LOGO, "image/png")},
        headers=auth_headers(user.json()["access_token"]),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_permissions"


async def test_admin_uploads_site_logo_for_public_readers(client, admin_headers):
    headers = await admin_headers()
    response = await client.put(
        "/api/admin/site-branding/logo",
        files={"file": ("logo.png", PNG_LOGO, "image/png")},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["is_custom_logo"] is True
    assert response.json()["logo_url"].startswith("/api/site-branding/logo?v=")

    unversioned_logo = await client.get("/api/site-branding/logo")
    assert unversioned_logo.status_code == 200
    assert unversioned_logo.content == PNG_LOGO
    assert unversioned_logo.headers["cache-control"] == "no-store"

    logo = await client.get(response.json()["logo_url"])
    assert logo.status_code == 200
    assert logo.content == PNG_LOGO
    assert logo.headers["content-type"] == "image/png"
    assert "immutable" in logo.headers["cache-control"]
    assert logo.headers["x-content-type-options"] == "nosniff"

    replacement = b"\xff\xd8\xff" + b"replacement-logo"
    replaced = await client.put(
        "/api/admin/site-branding/logo",
        files={"file": ("replacement.jpg", replacement, "image/jpeg")},
        headers=headers,
    )
    current_logo = await client.get(replaced.json()["logo_url"])

    assert replaced.status_code == 200
    assert current_logo.content == replacement
    assert current_logo.headers["content-type"] == "image/jpeg"


async def test_admin_upload_rejects_non_image_content(client, admin_headers):
    response = await client.put(
        "/api/admin/site-branding/logo",
        files={"file": ("logo.png", b"not actually an image", "image/png")},
        headers=await admin_headers(),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "site_logo_invalid_type"


async def test_admin_upload_rejects_logo_over_two_megabytes(client, admin_headers):
    response = await client.put(
        "/api/admin/site-branding/logo",
        files={
            "file": (
                "logo.png",
                b"\x89PNG\r\n\x1a\n" + b"x" * (2 * 1024 * 1024),
                "image/png",
            )
        },
        headers=await admin_headers(),
    )

    assert response.status_code == 413


async def test_admin_restores_default_site_logo(client, admin_headers):
    headers = await admin_headers()
    await client.put(
        "/api/admin/site-branding/logo",
        files={"file": ("logo.png", PNG_LOGO, "image/png")},
        headers=headers,
    )

    response = await client.delete(
        "/api/admin/site-branding/logo",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["logo_url"] == "/ApertureLogoFull.svg"
    assert response.json()["is_custom_logo"] is False
