from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import os
import importlib.util

from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from bramanda.email_config import load_local_env, smtp_config


SMTP_OPTIONS = smtp_config({'EMAIL_HOST_USER': 'sender@example.com',
                            'EMAIL_HOST_PASSWORD': 'fake-test-secret'})
SMTP_MAILERS = {'default': {'BACKEND': 'django.core.mail.backends.smtp.EmailBackend',
                            'OPTIONS': SMTP_OPTIONS}}


class ConfigurationTests(SimpleTestCase):
    def test_clean_local_settings_use_sqlite_console_email_and_local_origin(self):
        spec = importlib.util.spec_from_file_location(
            'bramanda.local_settings_test', Path(__file__).resolve().parent.parent / 'bramanda/settings.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, {}, clear=True), patch('bramanda.email_config.load_local_env'):
            spec.loader.exec_module(module)
        config = vars(module)
        self.assertTrue(config['DEBUG'])
        self.assertEqual(config['DATABASES']['default']['ENGINE'], 'django.db.backends.sqlite3')
        self.assertEqual(config['MAILERS']['default']['BACKEND'], 'django.core.mail.backends.console.EmailBackend')
        self.assertEqual(config['PUBLIC_BASE_URL'], 'http://127.0.0.1:8000')
        self.assertEqual(config['ALLOWED_HOSTS'], ['localhost', '127.0.0.1', '192.168.1.72'])

    def test_ports_and_boolean_validation(self):
        for port in (465, 587):
            options = smtp_config({'EMAIL_PORT': str(port)})
            self.assertEqual(options['use_ssl'], port == 465)
            self.assertEqual(options['use_tls'], port == 587)
        for env in ({'EMAIL_USE_SSL': 'True', 'EMAIL_USE_TLS': 'True'},
                    {'EMAIL_PORT': '465', 'EMAIL_USE_SSL': 'False'},
                    {'EMAIL_PORT': '587', 'EMAIL_USE_TLS': 'False'},
                    {'EMAIL_USE_SSL': 'typo'}, {'EMAIL_PORT': 'secret'},
                    {'EMAIL_TIMEOUT': '0'}):
            with self.subTest(env=env), self.assertRaises(ImproperlyConfigured):
                smtp_config(env)

    def test_password_normalization_only_for_gmail(self):
        self.assertEqual(smtp_config({'EMAIL_HOST_PASSWORD': 'abcd efgh ijkl mnop'})['password'],
                         'abcdefghijklmnop')
        self.assertEqual(smtp_config({'EMAIL_HOST': 'smtp.example.com',
                                     'EMAIL_HOST_PASSWORD': 'keep spaces'})['password'], 'keep spaces')

    def test_env_is_literal_and_does_not_override_process(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            path.write_text('# comment\nEMAIL_HOST_USER=file\nEMAIL_HOST_PASSWORD="$(literal)"\n', encoding='utf-8')
            env = {'EMAIL_HOST_USER': 'process'}
            load_local_env(path, env)
            self.assertEqual(env, {'EMAIL_HOST_USER': 'process', 'EMAIL_HOST_PASSWORD': '$(literal)'})
            path.write_text('secret-invalid-line', encoding='utf-8')
            with self.assertRaisesMessage(ImproperlyConfigured, 'line 1') as caught:
                load_local_env(path, {})
            self.assertNotIn('secret', str(caught.exception))


@override_settings(MAILERS=SMTP_MAILERS)
class SMTPTests(SimpleTestCase):
    def test_real_django_mailer_passes_options_and_credentials(self):
        backend = mail.mailers['default']
        for key, value in SMTP_OPTIONS.items():
            self.assertEqual(getattr(backend, key), value)
        with patch('django.core.mail.backends.smtp.smtplib.SMTP_SSL') as factory:
            backend.open()
            factory.assert_called_once()
            self.assertEqual(factory.call_args.args, ('smtp.gmail.com', 465))
            self.assertEqual(factory.call_args.kwargs['timeout'], 10)
            factory.return_value.login.assert_called_once_with('sender@example.com', 'fake-test-secret')
            factory.return_value.starttls.assert_not_called()
            backend.close()

    def test_django_starttls_before_login(self):
        config = {'default': {'BACKEND': SMTP_MAILERS['default']['BACKEND'],
                             'OPTIONS': {**SMTP_OPTIONS, 'port': 587, 'use_ssl': False, 'use_tls': True}}}
        with override_settings(MAILERS=config), patch('django.core.mail.backends.smtp.smtplib.SMTP') as factory:
            backend = mail.mailers['default']
            backend.open()
            self.assertEqual([call[0] for call in factory.return_value.method_calls], ['starttls', 'login'])
            backend.close()
