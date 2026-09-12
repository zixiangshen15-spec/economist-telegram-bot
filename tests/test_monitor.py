import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ['BOT_TOKEN'] = 'test-token-not-real'
os.environ['CHAT_ID'] = 'test-channel'
import monitor as bot


def issue(date):
    return {'name': 'te_' + date.replace('-', '.'), 'date': date}


def response(body):
    result = Mock()
    result.json.return_value = body
    result.iter_content.return_value = [b'test ebook']
    return result


class BotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.previous = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(os.chdir, self.previous)
        self.get = patch.object(bot.requests, 'get').start()
        self.post = patch.object(bot.requests, 'post').start()
        self.addCleanup(patch.stopall)
        self.get.side_effect = AssertionError('Unexpected GET')
        self.post.side_effect = AssertionError('Unexpected POST')
        patch.object(bot, 'log').start()

    def files(self, extensions=('epub', 'mobi')):
        return [{'type': 'file', 'name': 'issue.' + ext, 'size': 10,
                 'download_url': bot.RAW_BASE + '/te_2026.09.12/issue.' + ext}
                for ext in extensions]

    def test_dates_and_archive(self):
        self.get.side_effect = [response([
            {'type': 'dir', 'name': 'te_2026.09.12'},
            {'type': 'dir', 'name': 'te_2026.02.30'},
            {'type': 'dir', 'name': 'te_2026.9.5'},
            {'type': 'dir', 'name': 'fonts'},
            {'type': 'dir', 'name': '2025'}]),
            response([{'type': 'dir', 'name': 'te_2025.12.27'}])]
        result = bot.get_all_issue_dirs()
        self.assertEqual([x['date'] for x in result], ['2026-09-12', '2025-12-27'])
        self.assertEqual(result[1]['name'], '2025/te_2025.12.27')
        self.assertEqual(self.get.call_args_list[0].kwargs['params']['ref'], 'master')

    def test_empty_source_raises(self):
        self.get.side_effect = None
        self.get.return_value = response([])
        with self.assertRaises(RuntimeError):
            bot.get_all_issue_dirs()

    def test_selection(self):
        items = [issue('2026-09-12'), issue('2026-09-05'), issue('2026-07-04')]
        self.assertEqual(bot.select_new_issues(items, '2026-07-04', False), items[:1])
        self.assertEqual(bot.select_new_issues(items, '2026-07-04', True), list(reversed(items[:2])))
        self.assertEqual(bot.select_new_issues(items, '2026-09-12', True), [])
        self.assertEqual(bot.select_new_issues(items, '2026-09-19', False), [])

    def test_missing_or_cover_only_fails_before_send(self):
        for extensions in [(), ('jpg',)]:
            self.get.side_effect = [response(self.files(extensions))]
            with self.assertRaises(RuntimeError):
                bot.process_new_issue(issue('2026-09-12'))
        self.post.assert_not_called()

    def test_process_actual_formats(self):
        self.get.side_effect = [response(self.files()), response({}), response({})]
        self.post.side_effect = None
        self.post.return_value = response({'ok': True, 'result': {'message_id': 42}})
        self.assertTrue(bot.process_new_issue(issue('2026-09-12')))
        methods = [x.args[0].rsplit('/', 1)[-1] for x in self.post.call_args_list]
        self.assertEqual(methods, ['sendDocument', 'sendDocument', 'sendMessage'])
        summary = self.post.call_args.kwargs['json']['text']
        self.assertIn('EPUB', summary)
        self.assertNotIn('PDF', summary)

    def test_send_failure_raises(self):
        self.post.side_effect = None
        self.post.return_value = response({'ok': False, 'description': 'denied'})
        with self.assertRaises(RuntimeError):
            bot.send_message('hello')

    def test_transport_error_hides_token(self):
        self.post.side_effect = bot.requests.ConnectionError(bot.TELEGRAM_API)
        with self.assertRaises(RuntimeError) as ctx:
            bot.send_message('hello')
        self.assertNotIn(bot.BOT_TOKEN, str(ctx.exception))

    def test_partial_download_does_not_send(self):
        self.get.side_effect = [response(self.files()), response({}), bot.requests.Timeout()]
        with self.assertRaises(Exception):
            bot.process_new_issue(issue('2026-09-12'))
        self.post.assert_not_called()

    def test_catalog_failed_pin_preserves_old(self):
        Path(bot.CATALOG_FILE).write_text('176')
        self.post.side_effect = [response({'ok': True, 'result': {'message_id': 200}}),
                                 response({'ok': False, 'description': 'pin denied'})]
        with self.assertRaises(RuntimeError):
            bot.update_pinned_catalog([issue('2026-09-12')])
        self.assertEqual(Path(bot.CATALOG_FILE).read_text(), '176')
        self.assertFalse(any(c.args[0].endswith('/unpinChatMessage') for c in self.post.call_args_list))

    def test_catalog_save_failure_preserves_old(self):
        Path(bot.CATALOG_FILE).write_text('176')
        self.post.side_effect = None
        self.post.return_value = response({'ok': True, 'result': {'message_id': 200}})
        with patch.object(bot, 'atomic_write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                bot.update_pinned_catalog([issue('2026-09-12')])
        self.assertEqual(Path(bot.CATALOG_FILE).read_text(), '176')
        self.assertFalse(any(c.args[0].endswith('/unpinChatMessage') for c in self.post.call_args_list))

    def test_catalog_success(self):
        Path(bot.CATALOG_FILE).write_text('176')
        self.post.side_effect = None
        self.post.return_value = response({'ok': True, 'result': {'message_id': 200}})
        self.assertTrue(bot.update_pinned_catalog([issue('2026-09-12')]))
        self.assertEqual(Path(bot.CATALOG_FILE).read_text(), '200')
        methods = [c.args[0].rsplit('/', 1)[-1] for c in self.post.call_args_list]
        self.assertEqual(methods, ['sendMessage', 'pinChatMessage', 'unpinChatMessage'])

    def test_catalog_links_and_split(self):
        items = [issue('2026-09-12')] * 100
        pages = bot.generate_catalog_messages(items)
        self.assertGreater(len(pages), 1)
        self.assertTrue(all(len(p) <= 3500 for p in pages))
        self.assertIn('hehonghui/awesome-english-ebooks/tree/master/01_economist/te_2026.09.12', pages[0])
        self.assertNotIn('PDF /', pages[0])

    def test_main_migration_then_dedup(self):
        Path(bot.STATE_FILE).write_text('2026-07-04')
        items = [issue('2026-09-12'), issue('2026-09-05')]
        with patch.object(bot, 'get_all_issue_dirs', return_value=items), \
                patch.object(bot, 'process_new_issue', return_value=True) as send, \
                patch.object(bot, 'get_issue_files', return_value={'epub': {}}), \
                patch.object(bot, 'update_pinned_catalog', return_value=True):
            self.assertEqual(bot.main(), 0)
            send.assert_called_once_with(items[0])
            self.assertEqual(Path(bot.STATE_FILE).read_text(), '2026-09-12')
            self.assertEqual(Path(bot.SOURCE_STATE_FILE).read_text(), bot.SOURCE_ID)
            send.reset_mock()
            self.assertEqual(bot.main(), 0)
            send.assert_not_called()

    def test_main_failed_send_preserves_migration(self):
        Path(bot.STATE_FILE).write_text('2026-07-04')
        with patch.object(bot, 'get_all_issue_dirs', return_value=[issue('2026-09-12')]), \
                patch.object(bot, 'process_new_issue', return_value=False):
            self.assertEqual(bot.main(), 1)
        self.assertEqual(Path(bot.STATE_FILE).read_text(), '2026-07-04')
        self.assertFalse(Path(bot.SOURCE_STATE_FILE).exists())

    def test_main_checkpoint_stops_at_failure(self):
        Path(bot.STATE_FILE).write_text('2026-08-29')
        Path(bot.SOURCE_STATE_FILE).write_text(bot.SOURCE_ID)
        items = [issue('2026-09-19'), issue('2026-09-12'), issue('2026-09-05')]
        with patch.object(bot, 'get_all_issue_dirs', return_value=items), \
                patch.object(bot, 'process_new_issue', side_effect=[True, False]) as send:
            self.assertEqual(bot.main(), 1)
        self.assertEqual(Path(bot.STATE_FILE).read_text(), '2026-09-05')
        self.assertEqual(send.call_count, 2)

    def test_main_empty_fails(self):
        with patch.object(bot, 'get_all_issue_dirs', return_value=[]):
            self.assertEqual(bot.main(), 1)

    def test_atomic_state(self):
        Path(bot.STATE_FILE).write_text('2026-07-04')
        with patch.object(bot.os, 'replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                bot.save_last_processed('2026-09-12')
        self.assertEqual(Path(bot.STATE_FILE).read_text(), '2026-07-04')

    def test_end_to_end_migration_mocked_network(self):
        Path(bot.STATE_FILE).write_text('2026-07-04')
        Path(bot.CATALOG_FILE).write_text('176')
        self.get.side_effect = [response([
            {'type': 'dir', 'name': 'te_2026.09.12'},
            {'type': 'dir', 'name': 'te_2026.09.05'}]),
            response(self.files()), response({}), response({})]
        self.post.side_effect = None
        self.post.return_value = response({'ok': True, 'result': {'message_id': 200}})
        self.assertEqual(bot.main(), 0)
        self.assertEqual(Path(bot.STATE_FILE).read_text(), '2026-09-12')
        self.assertEqual(Path(bot.CATALOG_FILE).read_text(), '200')
        self.assertEqual(Path(bot.SOURCE_STATE_FILE).read_text(), bot.SOURCE_ID)
        self.assertEqual(sum(c.args[0].endswith('/sendDocument') for c in self.post.call_args_list), 2)
        self.assertFalse(any('te_2026.09.05/' in c.args[0] for c in self.get.call_args_list))

    def test_end_to_end_partial_send_no_checkpoint(self):
        Path(bot.STATE_FILE).write_text('2026-07-04')
        Path(bot.CATALOG_FILE).write_text('176')
        self.get.side_effect = [response([{'type': 'dir', 'name': 'te_2026.09.12'}]),
            response(self.files()), response({}), response({})]
        self.post.side_effect = [response({'ok': True}), response({'ok': False})]
        self.assertEqual(bot.main(), 1)
        self.assertEqual(Path(bot.STATE_FILE).read_text(), '2026-07-04')
        self.assertEqual(Path(bot.CATALOG_FILE).read_text(), '176')
        self.assertFalse(Path(bot.SOURCE_STATE_FILE).exists())
        self.assertEqual(self.post.call_count, 2)

    def test_catalog_unpin_failure_tracks_both(self):
        Path(bot.CATALOG_FILE).write_text('176')
        self.post.side_effect = [response({'ok': True, 'result': {'message_id': 200}}),
                                 response({'ok': True}), response({'ok': False})]
        with self.assertRaises(RuntimeError):
            bot.update_pinned_catalog([issue('2026-09-12')])
        self.assertEqual(Path(bot.CATALOG_FILE).read_text(), '200\n176')

    def test_second_catalog_page_failure_preserves_old(self):
        Path(bot.CATALOG_FILE).write_text('176')
        self.post.side_effect = [response({'ok': True, 'result': {'message_id': 200}}),
                                 response({'ok': True}), response({'ok': False})]
        with self.assertRaises(RuntimeError):
            bot.update_pinned_catalog([issue('2026-09-12')] * 100)
        self.assertEqual(Path(bot.CATALOG_FILE).read_text(), '176')
        self.assertFalse(any(c.args[0].endswith('/unpinChatMessage') for c in self.post.call_args_list))

    def test_invalid_metadata(self):
        for item in [{**self.files()[0], 'name': '../bad.epub'},
                     {**self.files()[0], 'size': 0},
                     {**self.files()[0], 'download_url': None}]:
            self.get.side_effect = [response([item])]
            with self.assertRaises(RuntimeError):
                bot.get_issue_files('te_2026.09.12')

    def test_duplicate_formats_reported(self):
        self.get.side_effect = [response([self.files()[0], self.files()[0]])]
        with self.assertRaises(RuntimeError):
            bot.get_issue_files('te_2026.09.12')

    def test_wrong_directory_response(self):
        self.get.side_effect = [response({'message': 'not a directory'})]
        with self.assertRaises(RuntimeError):
            bot.get_all_issue_dirs()

    def test_github_token_only_on_api(self):
        self.get.side_effect = [response(self.files()), response({})]
        with patch.dict(os.environ, {'GITHUB_TOKEN': 'fake-github-token'}):
            files = bot.get_issue_files('te_2026.09.12')
            bot.download_file(files['epub']['download_url'], 'test.epub')
        self.assertIn('Authorization', self.get.call_args_list[0].kwargs['headers'])
        self.assertNotIn('headers', self.get.call_args_list[1].kwargs)

    def test_oversize_link_failure(self):
        Path('test.epub').write_bytes(b'fake')
        self.post.side_effect = [response({'ok': False})]
        with patch.object(bot, 'TELEGRAM_MAX_SIZE', 1):
            with self.assertRaises(RuntimeError):
                bot.send_issue_files(issue('2026-09-12'),
                    {'epub': {'download_url': bot.RAW_BASE + '/test.epub'}}, [('epub', 'test.epub')])
            with self.assertRaises(RuntimeError):
                bot.send_document('test.epub')

    def test_cover_caption_actual_formats(self):
        self.get.side_effect = [response(self.files(('jpg', 'epub'))), response({}), response({})]
        self.post.side_effect = None
        self.post.return_value = response({'ok': True})
        self.assertTrue(bot.process_new_issue(issue('2026-09-12')))
        caption = self.post.call_args_list[0].kwargs['data']['caption']
        self.assertIn('EPUB', caption)
        self.assertNotIn('PDF', caption)

    def test_truncated_download_no_send(self):
        self.get.side_effect = [response([{**self.files()[0], 'size': 999}]), response({})]
        with self.assertRaises(RuntimeError):
            bot.process_new_issue(issue('2026-09-12'))
        self.post.assert_not_called()

    def test_missing_credentials(self):
        with patch.object(bot, 'BOT_TOKEN', ''):
            self.assertEqual(bot.main(), 1)
        self.get.assert_not_called()

    def test_missing_and_invalid_state(self):
        self.assertEqual(bot.get_last_processed(), '')
        for value in ['bad-date', '2026-02-30', '2026-9-12']:
            Path(bot.STATE_FILE).write_text(value)
            with self.assertRaises(RuntimeError):
                bot.get_last_processed()
        Path(bot.STATE_FILE).write_text('2026-02-30')
        with self.assertRaises(RuntimeError):
            bot.get_last_processed()

    def test_catalog_bad_id_fails_before_send(self):
        Path(bot.CATALOG_FILE).write_text('not-an-id')
        with self.assertRaises(RuntimeError):
            bot.update_pinned_catalog([issue('2026-09-12')])
        self.post.assert_not_called()

    def test_catalog_missing_returned_id(self):
        self.post.side_effect = [response({'ok': True, 'result': {}})]
        with self.assertRaises(RuntimeError):
            bot.update_pinned_catalog([issue('2026-09-12')])
        self.assertFalse(Path(bot.CATALOG_FILE).exists())


if __name__ == '__main__':
    unittest.main()
