# ruff: noqa: INP001  # Standalone executable module.
import json
import logging
import sys
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from random import SystemRandom
from urllib.parse import parse_qs, unquote, urlsplit

HOST = '0.0.0.0'  # noqa: S104  # nosec B104  # Listen on container interfaces.
PORT = 8081
MIN_TEMPERATURE = 18.0
MAX_TEMPERATURE = 30.0
ROOMS = {'1': 'Living Room', '2': 'Bedroom', '3': 'Kitchen'}
logger = logging.getLogger(__name__)


def make_measurement(location: str = '', sensor_id: str = '') -> dict[str, str | float]:
    """Generate a temperature reading for a room or sensor identifier.

    Args:
        location: Room name; defaults to the sensor's room or Unknown.
        sensor_id: Sensor identifier; defaults to the room's identifier or 0.

    Returns:
        A new reading in the format consumed by the smart home application.
    """
    if not location:
        location = ROOMS.get(sensor_id, 'Unknown')
    if not sensor_id:
        sensor_id = next((key for key, room in ROOMS.items() if room == location), '0')
    return {
        'value': SystemRandom().uniform(MIN_TEMPERATURE, MAX_TEMPERATURE),
        'unit': '\u00b0C',
        'timestamp': datetime.now(UTC).isoformat(),
        'location': location,
        'status': 'active',
        'sensor_id': sensor_id,
        'sensor_type': 'temperature',
        'description': f'Temperature in {location}',
    }


class TemperatureServer(ThreadingHTTPServer):
    def handle_error(self, _request, _client_address):
        """Report the failure class without request data or peer addresses."""
        logger.error('HTTP request failed: %s', type(sys.exception()).__name__)


class TemperatureHandler(BaseHTTPRequestHandler):
    # pylint: disable-next=invalid-name  # Required by BaseHTTPRequestHandler.
    def do_GET(self):
        try:
            request = urlsplit(self.path)
        except ValueError:
            self._send_json(HTTPStatus.BAD_REQUEST, {'detail': 'Invalid request target'})
            return
        sensor_id = unquote(request.path.removeprefix('/temperature/'))
        if request.path == '/temperature':
            sensor_id = ''
        elif not request.path.startswith('/temperature/') or not sensor_id or '/' in sensor_id:
            self._send_json(HTTPStatus.NOT_FOUND, {'detail': 'Not found'})
            return
        location = parse_qs(request.query).get('location', [''])[0]
        self._send_json(HTTPStatus.OK, make_measurement(location, sensor_id))

    def _send_json(self, status: HTTPStatus, payload: dict[str, str | float]):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-cache, no-store')
        self.end_headers()
        self.wfile.write(body)

    # pylint: disable-next=arguments-differ  # Base logger arguments are intentionally unused.
    def log_message(self, _format, *_args):
        """Keep request paths and client addresses out of application logs."""
        return


if __name__ == '__main__':
    with TemperatureServer((HOST, PORT), TemperatureHandler) as server:
        server.serve_forever()
