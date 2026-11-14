# ruff: noqa: INP001  # Unittest discovery loads this script without a package.
import json
import unittest
from contextlib import redirect_stderr
from datetime import datetime
from http.client import HTTPConnection
from io import StringIO
from socket import create_connection
from threading import Thread

from main import TemperatureHandler, TemperatureServer


class TemperatureAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = TemperatureServer(('127.0.0.1', 0), TemperatureHandler)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.thread.join(timeout=5)
        cls.server.server_close()

    def get(self, path):
        connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            connection.request('GET', path)
            response = connection.getresponse()
            return response.status, response.headers, json.loads(response.read())
        finally:
            connection.close()

    def test_location_identifies_sensor(self):
        for location, sensor_id in [
            ('Living%20Room', '1'),
            ('Bedroom', '2'),
            ('Kitchen', '3'),
            ('Garage', '0'),
        ]:
            with self.subTest(location=location):
                status, _, reading = self.get(f'/temperature?location={location}')
                assert status == 200
                assert reading['sensor_id'] == sensor_id
                assert reading['location'] == location.replace('%20', ' ')

    def test_sensor_id_selects_default_room(self):
        for sensor_id, location in [('1', 'Living Room'), ('2', 'Bedroom'), ('3', 'Kitchen'), ('42', 'Unknown')]:
            with self.subTest(sensor_id=sensor_id):
                status, _, reading = self.get(f'/temperature/{sensor_id}')
                assert status == 200
                assert reading['sensor_id'] == sensor_id
                assert reading['location'] == location

    def test_missing_identity_uses_unknown_room(self):
        for path in ['/temperature', '/temperature?location=']:
            with self.subTest(path=path):
                status, _, reading = self.get(path)
                assert status == 200
                assert reading['sensor_id'] == '0'
                assert reading['location'] == 'Unknown'

    def test_explicit_location_overrides_default_room(self):
        status, _, reading = self.get('/temperature/1?location=Kitchen')
        assert status == 200
        assert reading['sensor_id'] == '1'
        assert reading['location'] == 'Kitchen'

    def test_response_is_compatible_with_monolith(self):
        status, headers, reading = self.get('/temperature/1')
        assert status == 200
        assert headers['Content-Type'] == 'application/json'
        assert headers['Cache-Control'] == 'no-cache, no-store'
        assert isinstance(reading['value'], (int, float))
        assert reading['unit'] == '°C'
        assert reading['status'] == 'active'
        assert reading['sensor_type'] == 'temperature'
        assert isinstance(reading['description'], str)
        assert datetime.fromisoformat(reading['timestamp']).utcoffset().total_seconds() == 0

    def test_readings_are_generated_for_every_request(self):
        values = [self.get('/temperature/1')[2]['value'] for _ in range(5)]
        assert len(set(values)) > 1
        assert all(18 <= value <= 30 for value in values)

    def test_unknown_paths_return_json_not_found(self):
        for path in ['/', '/temperature/', '/temperature/1/extra']:
            with self.subTest(path=path):
                status, headers, body = self.get(path)
                assert status == 404
                assert headers['Content-Type'] == 'application/json'
                assert body == {'detail': 'Not found'}

    def test_malformed_request_target_returns_json_without_error_log(self):
        errors = StringIO()
        with (
            redirect_stderr(errors),
            create_connection(('127.0.0.1', self.server.server_port), timeout=5) as connection,
        ):
            connection.sendall(b'GET http://[ HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n')
            with connection.makefile('rb') as response_stream:
                response = response_stream.read()
        assert response.startswith(b'HTTP/1.0 400')
        assert json.loads(response.split(b'\r\n\r\n', 1)[1]) == {'detail': 'Invalid request target'}
        assert errors.getvalue() == ''

    def test_server_errors_do_not_log_client_address_or_exception_text(self):
        error_message = 'private-request-data'
        with redirect_stderr(StringIO()), self.assertLogs('main', level='ERROR') as captured:
            try:
                raise ConnectionResetError(error_message)  # noqa: TRY301 - Exercise an active exception.
            except ConnectionResetError:
                self.server.handle_error(None, ('192.0.2.10', 12345))
        assert len(captured.records) == 1
        message = captured.records[0].getMessage()
        assert 'ConnectionResetError' in message
        assert '192.0.2.10' not in message
        assert error_message not in message
        assert captured.records[0].exc_info is None


if __name__ == '__main__':
    unittest.main()
