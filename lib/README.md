# prusa-connect

Async Python client for the [Prusa Connect](https://github.com/prusa3d/prusa-connect)
HTTP API (`/api/v1`) and its server-sent event stream.

```python
import aiohttp
from prusa_connect import PrusaConnect, StreamConnected, Event

async with aiohttp.ClientSession() as session:
    client = PrusaConnect(
        session, "https://connect.local:8080", token="pcl_…", fingerprint="AB:CD:…"
    )  # optional certificate pin
    devices = {d.id: d for d in await client.devices()}
    async for item in client.events():
        if isinstance(item, StreamConnected) and item.reconnect:
            devices = {d.id: d for d in await client.devices()}  # telemetry is not replayed
        elif isinstance(item, Event) and item.type.endswith("telemetry.sampled"):
            devices[item.device_id].apply(item.data["path"], item.data.get("value"))
```

What it covers:

- `health()`, `app_settings()`, `device_states()`
- `devices()` (walks every page), `device(id)`, with the tool tree read from the state tree
  (`Device.tools`, 0-based ids such as `0` and `0.2`)
- `command()` with an idempotency key, and `pause_print`, `resume_print`, `stop_print`,
  `set_nozzle_temperature(device, celsius, tool="1")`, `set_bed_temperature`, `set_chamber_temperature`, `set_chamber_fan` (`None` is automatic), `set_chamber_light`, `set_speed`;
  the value argument is read from the device's capability set
- `cameras()`, `snapshot()` (honours 204 and `If-Modified-Since`), `camera_stream()`
- `events()`: reconnects with backoff, resumes with `Last-Event-ID`, yields
  `StreamConnected` / `StreamDisconnected` so a caller refetches after a gap, raises
  `AuthenticationError` on 401 or an `auth.expired` frame
- `fetch_certificate_fingerprint()` and `fingerprint=` for trusting a deployment's own CA
  by pinning the server certificate
- app pairing (RFC 8628 device authorization), so nobody pastes a token:

  ```python
  client = PrusaConnect(session, "https://connect.local:8080")  # no token yet
  pairing = await client.request_app_pairing("My app", [SCOPE_OPERATE])
  print(f"Open {pairing.verification_uri_complete} and approve {pairing.user_code}")
  token = await client.wait_for_app_pairing(pairing)  # PairingDeniedError, PairingExpiredError
  ```

The package lives in the Home Assistant integration repository for now and is laid out to
move to its own repository and PyPI unchanged. Licence: MIT.
