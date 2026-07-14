import unittest
from unittest.mock import patch

from webhook import WebhookClient


class WebhookClientTests(unittest.TestCase):
    def test_send_immediate_posts_to_all_configured_urls(self):
        client = WebhookClient(['https://dev.example', 'https://prod.example'])

        with patch('webhook.requests.post') as mock_post:
            mock_post.return_value.status_code = 200

            client.send_immediate('pump_status', {'running': True})

        self.assertEqual(mock_post.call_count, 2)
        self.assertEqual(
            mock_post.call_args_list[0].args[0],
            'https://dev.example/webhook/pump-status',
        )
        self.assertEqual(
            mock_post.call_args_list[1].args[0],
            'https://prod.example/webhook/pump-status',
        )


if __name__ == '__main__':
    unittest.main()
