"""Pinned real codec only; no socket, process or simulation factories."""
import copy
import unittest

try:
    from pymavlink.dialects.v20 import common as mav
except ImportError as exc:
    raise unittest.SkipTest('run real codec suite in WSL') from exc

from tools.benchmark.openvins_timesync_wire import PinnedCodec


class IntervalCodecTests(unittest.TestCase):
    def setUp(self):
        self.codec = PinnedCodec()
        self.assertTrue(callable(getattr(self.codec, 'encode_interval_command', None)),
                        'pinned interval command encoder missing')
        self.assertTrue(callable(getattr(self.codec, 'interval_response', None)),
                        'pinned interval response validator missing')

    def row(self, message, *, system=9, component=1, v1=False):
        raw = message.pack(mav.MAVLink(None, srcSystem=system, srcComponent=component), force_mavlink1=v1)
        return self.codec.decode_datagram(raw)[0]

    def ack(self, command=510, result=0, **kw):
        return self.row(mav.MAVLink_command_ack_message(command, result, 0, 0, 254, 191), **kw)

    def test_get_and_set_bytes_target_parameters_sequence(self):
        for operation, interval, command in [('get', None, 510), ('set', 10000, 511), ('set', 100000, 511)]:
            with self.subTest(operation=operation, interval=interval):
                raw = self.codec.encode_interval_command(operation, interval, 253)
                msg = mav.MAVLink(None).decode(bytearray(raw))
                self.assertEqual((msg.get_srcSystem(), msg.get_srcComponent(), msg.get_seq()), (254, 191, 253))
                self.assertEqual((msg.target_system, msg.target_component, msg.command, msg.confirmation), (9, 1, command, 0))
                self.assertEqual([getattr(msg, 'param' + str(i)) for i in range(1, 8)],
                                 [111, interval or 0, 0, 0, 0, 0, 0])

    def test_invalid_operations_intervals_and_sequences(self):
        for op, value, seq in [('get', 1, 0), ('set', None, 0), ('set', True, 0), ('set', 0, 0),
                               ('set', -1, 0), ('set', 16777217, 0), ('other', None, 0),
                               ('get', None, True), ('get', None, -1), ('get', None, 256)]:
            with self.subTest(args=(op, value, seq)), self.assertRaises(ValueError):
                self.codec.encode_interval_command(op, value, seq)

    def test_ack_and_interval_preserve_semantics(self):
        for command in [510, 511]:
            for result in [0, 1, 2, 3, 4, 6]:
                parsed = self.codec.interval_response(self.ack(command, result))
                self.assertEqual(parsed, {'kind': 'ack', 'command': command, 'result': result})
        parsed = self.codec.interval_response(self.row(mav.MAVLink_message_interval_message(111, 100000)))
        self.assertEqual(parsed, {'kind': 'interval', 'message_id': 111, 'interval_us': 100000})

    def test_wrong_source_v1_and_target_refused(self):
        rows = [self.ack(system=8), self.ack(component=2), self.ack(v1=True),
                self.row(mav.MAVLink_command_ack_message(511, 0)),
                self.row(mav.MAVLink_command_ack_message(511, 0, 0, 0, 254, 190)),
                self.row(mav.MAVLink_command_ack_message(400, 0, 0, 0, 254, 191)),
                self.row(mav.MAVLink_command_ack_message(511, 5, 50, 0, 254, 191))]
        for row in rows:
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.codec.interval_response(row)

    def test_interval_unknown_nonrestorable_and_schema_refused(self):
        for mid, value in [(110, 10000), (111, -1), (111, 0), (111, 16777217)]:
            with self.subTest(mid=mid, value=value), self.assertRaises(ValueError):
                self.codec.interval_response(self.row(mav.MAVLink_message_interval_message(mid, value)))
        for key, value in [('system', True), ('sequence', True), ('framing', 2.0)]:
            row = self.ack()
            row[key] = value
            with self.assertRaises(ValueError):
                self.codec.interval_response(row)
        row = self.ack()
        row['fields']['command'] = 510.0
        with self.assertRaises(ValueError):
            self.codec.interval_response(row)
        row = self.ack()
        row['fields']['extra'] = 0
        with self.assertRaises(ValueError):
            self.codec.interval_response(row)

    def test_input_not_mutated(self):
        row = self.ack()
        before = copy.deepcopy(row)
        self.codec.interval_response(row)
        self.assertEqual(row, before)

    def test_real_codec_exchange_mixed_heartbeat_and_reply_order(self):
        from tools.benchmark.openvins_timesync_interval import IntervalExchange

        for reverse in (False, True):
            sent, heartbeats = [], []
            sequence = [41]
            def send(operation, value, sequence=sequence, sent=sent):
                raw = self.codec.encode_interval_command(operation, value, sequence[0])
                sent.append(self.codec.decode_datagram(raw)[0])
                sequence[0] = (sequence[0] + 1) % 256
            exchange = IntervalExchange(send, lambda stopping: None, lambda: 100, 100)
            def route(*messages, exchange=exchange, heartbeats=heartbeats):
                encoder = mav.MAVLink(None, srcSystem=9, srcComponent=1)
                raw = b''.join(msg.pack(encoder) for msg in messages)
                # One decode, no receive call. This is an injected test loop,
                # not the actual observed/capture receive-owner integration.
                for row in self.codec.decode_datagram(raw):
                    if row['type'] == 'HEARTBEAT':
                        heartbeats.append(row)
                    else:
                        exchange.feed(self.codec.interval_response(row), 100)
            def answer(value, reverse=reverse, route=route):
                interval = mav.MAVLink_message_interval_message(111, value)
                ack = mav.MAVLink_command_ack_message(510, 0, 0, 0, 254, 191)
                hb = mav.MAVLink_heartbeat_message(2, 12, 0, 0, 3, 3)
                route(*([ack, hb, interval] if reverse else [interval, hb, ack]))
            exchange.poll()
            answer(100000)
            exchange.poll()
            exchange.poll()
            route(mav.MAVLink_command_ack_message(511, 0, 0, 0, 254, 191))
            exchange.poll()
            exchange.poll()
            answer(10000)
            exchange.poll()
            exchange.body_complete(True)
            exchange.poll()
            route(mav.MAVLink_command_ack_message(511, 0, 0, 0, 254, 191))
            exchange.poll()
            for _ in range(2):
                exchange.poll()
                answer(100000)
                exchange.poll()
            self.assertTrue(exchange.evidence['modeled_transaction_pass'])
            self.assertEqual(len(heartbeats), 4)
            self.assertEqual([row['sequence'] for row in sent], list(range(41, 47)))
            self.assertEqual([row['fields']['command'] for row in sent], [510, 511, 510, 511, 510, 510])
