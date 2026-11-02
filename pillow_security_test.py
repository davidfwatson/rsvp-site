"""Keep hostile EXIF metadata bounded while accepting ordinary phone photos."""
from io import BytesIO
import struct

from PIL import Image
import pytest

import app as app_module
from event_config import save_event_config


@pytest.fixture
def image_client(monkeypatch):
    """Authenticate a host against isolated event and upload stores."""
    import passkey_auth

    save_event_config([dict(id='photo-event', slug='photo-event', name='Photo event')])
    monkeypatch.setattr(passkey_auth, '_load_data', lambda: dict(
        admins=[dict(id='photo-host', name='Photo host', is_owner=False)], invites=[]))
    client = app_module.app.test_client()
    with client.session_transaction() as session:
        session['admin_id'] = 'photo-host'
    return client


@pytest.mark.parametrize('endpoint', ['/admin/photo-event/upload', '/api/mobile/events/photo-event/upload'])
def test_upload_rejects_repeated_exif_headers(image_client, endpoint):
    """Reject the EXIF header pattern behind CVE-2026-96643 using tiny input."""
    buffer = BytesIO()
    # Pillow removes one prefix when saving PNG. Three remain in the file,
    # exceeding the patched parser's bound without building a large CPU payload.
    Image.new('RGB', (1, 1)).save(buffer, 'PNG', exif=b'Exif\x00\x00' * 4)
    response = image_client.post(endpoint, data={'image': (BytesIO(buffer.getvalue()), 'photo.png')})
    assert response.status_code == 400
    assert 'valid JPEG, PNG, or WebP' in response.json['error']


def test_exif_tag_values_cannot_amplify_the_metadata_buffer():
    """Overlapping IFD values must stay within the source metadata byte budget."""
    count, value_size = 4, 64
    offset = 8 + 2 + count * 12 + 4
    # Each distinct tag points to the same 64-byte value. The old parser retained
    # all four copies; large versions of this layout caused memory exhaustion.
    data = (b'II\x2a\x00' + struct.pack('<IH', 8, count)
            + b''.join(struct.pack('<HHII', 65000 + i, 7, value_size, offset) for i in range(count))
            + struct.pack('<I', 0) + b'x' * value_size)
    exif = Image.Exif()
    with pytest.warns(UserWarning, match='Tag data larger than file'):
        exif.load(data)
    assert sum(len(value) for value in exif.values()) <= len(data)


@pytest.mark.parametrize('image_format', ['JPEG', 'PNG', 'WEBP'])
def test_phone_photo_orientation_and_metadata_stripping(image_client, image_format):
    """The patched decoder keeps supported phone photos oriented and private."""
    buffer = BytesIO()
    exif = Image.Exif()
    exif[274] = 6  # Rotate 90 degrees clockwise.
    exif[270] = 'private camera metadata'
    Image.new('RGB', (40, 20), 'orange').save(buffer, image_format, exif=exif)
    response = image_client.post('/admin/photo-event/upload', data={
        'image': (BytesIO(buffer.getvalue()), 'photo.' + image_format.lower())})
    assert response.status_code == 200
    with Image.open(BytesIO(image_client.get(response.json['url']).data)) as image:
        assert image.format == 'WEBP'
        assert image.size == (20, 40)
        assert not image.getexif()
