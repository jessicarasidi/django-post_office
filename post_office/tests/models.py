import json
from django.conf import settings as django_settings
from django.core import mail
from django.core.mail import EmailMultiAlternatives, get_connection
from django.test import TestCase
from django.test.utils import override_settings

from ..utils import send_mail
from ..models import Email, Log, STATUS, EmailTemplate
from ..mail import from_template, send


class ModelTest(TestCase):

    def test_email_message(self):
        """
        Test to make sure that model's "email_message" method
        returns proper ``EmailMultiAlternatives`` with html attachment.
        """

        email = Email.objects.create(to='to@example.com',
            from_email='from@example.com', subject='Subject',
            message='Message', html_message='<p>HTML</p>')
        message = email.email_message()
        self.assertTrue(isinstance(message, EmailMultiAlternatives))
        self.assertEqual(message.from_email, 'from@example.com')
        self.assertEqual(message.to, ['to@example.com'])
        self.assertEqual(message.subject, 'Subject')
        self.assertEqual(message.body, 'Message')
        self.assertEqual(message.alternatives, [('<p>HTML</p>', 'text/html')])

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_dispatch(self):
        """
        Ensure that email.dispatch() actually sends out the email
        """
        email = Email.objects.create(to='to@example.com', from_email='from@example.com',
                                     subject='Test dispatch', message='Message')
        email.dispatch()
        self.assertEqual(mail.outbox[0].subject, 'Test dispatch')

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_status_and_log(self):
        """
        Ensure that status and log are set properly on successful sending
        """
        email = Email.objects.create(to='to@example.com', from_email='from@example.com',
                                     subject='Test', message='Message')
        # Ensure that after dispatch status and logs are correctly set
        email.dispatch()
        log = Log.objects.latest('id')
        self.assertEqual(email.status, STATUS.sent)
        self.assertEqual(log.email, email)

    @override_settings(EMAIL_BACKEND='post_office.tests.backends.ErrorRaisingBackend')
    def test_status_and_log_on_error(self):
        """
        Ensure that status and log are set properly on sending failure
        """
        email = Email.objects.create(to='to@example.com', from_email='from@example.com',
                                     subject='Test', message='Message')
        # Ensure that after dispatch status and logs are correctly set
        email.dispatch()
        log = Log.objects.latest('id')
        self.assertEqual(email.status, STATUS.failed)
        self.assertEqual(log.email, email)
        self.assertEqual(log.status, STATUS.failed)
        self.assertEqual(log.message, 'Fake Error')

    def test_dispatch_uses_opened_connection(self):
        """
        Test that the ``dispatch`` method uses the argument supplied connection.
        We test this by overriding the email backend with a dummy backend,
        but passing in a previously opened connection from locmem backend.
        """
        email = Email.objects.create(to='to@example.com', from_email='from@example.com',
                                     subject='Test', message='Message')
        django_settings.EMAIL_BACKEND = \
            'django.core.mail.backends.dummy.EmailBackend'
        email.dispatch()
        # Outbox should be empty since dummy backend doesn't do anything
        self.assertEqual(len(mail.outbox), 0)

        # Message should go to outbox since locmem connection is explicitly passed in
        connection = get_connection('django.core.mail.backends.locmem.EmailBackend')
        email.dispatch(connection=connection)
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(EMAIL_BACKEND='random.backend')
    def test_errors_while_getting_connection_are_logged(self):
        """
        Ensure that status and log are set properly on sending failure
        """
        email = Email.objects.create(to='to@example.com', from_email='from@example.com',
                                     subject='Test', message='Message')
        # Ensure that after dispatch status and logs are correctly set
        email.dispatch()
        log = Log.objects.latest('id')
        self.assertEqual(email.status, STATUS.failed)
        self.assertEqual(log.email, email)
        self.assertEqual(log.status, STATUS.failed)
        self.assertIn('does not define a "backend" class', log.message)

    def test_from_template(self):
        """
        Test basic constructing email message with template
        """

        # Test 1, create email object from template, without context
        email_template = EmailTemplate.objects.create(name='welcome',
            subject='Welcome!', content='Hi there!')
        email = from_template('from@example.com', 'to@example.com', email_template)
        self.assertEqual(email.from_email, 'from@example.com')
        self.assertEqual(email.to, 'to@example.com')
        self.assertEqual(email.subject, 'Welcome!')
        self.assertEqual(email.message, 'Hi there!')

        # Passing in template name also works
        email = from_template('from2@example.com', 'to2@example.com',
                              email_template.name)
        self.assertEqual(email.from_email, 'from2@example.com')
        self.assertEqual(email.to, 'to2@example.com')
        self.assertEqual(email.subject, 'Welcome!')
        self.assertEqual(email.message, 'Hi there!')

        # Ensure that subject, message and html_message are correctly rendered
        email_template.subject = "Subject: {{foo}}"
        email_template.content = "Message: {{foo}}"
        email_template.html_content = "HTML: {{foo}}"
        email_template.save()
        email = from_template('from@example.com', 'to@example.com',
                              email_template, context={'foo': 'bar'})

        self.assertEqual(email.subject, 'Subject: bar')
        self.assertEqual(email.message, 'Message: bar')
        self.assertEqual(email.html_message, 'HTML: bar')

    def test_send_argument_checking(self):
        """
        mail.send() should raise an Exception if "template" argument is used
        with "subject", "message" or "html_message" arguments
        """
        self.assertRaises(ValueError, send, 'from@a.com', ['to@example.com'],
                          template='foo', subject='bar')
        self.assertRaises(ValueError, send, 'from@a.com', ['to@example.com'],
                          template='foo', message='bar')
        self.assertRaises(ValueError, send, 'from@a.com', ['to@example.com'],
                          template='foo', html_message='bar')

    def test_send_with_template(self):
        """
        Ensure mail.send correctly creates templated emails to recipients
        """
        Email.objects.all().delete()
        email_template = EmailTemplate.objects.create(name='foo', subject='bar',
                                                      content='baz')
        emails = send('from@a.com', ['to1@example.com', 'to2@example.com'],
                      template=email_template)
        self.assertEqual(len(emails), 2)
        self.assertEqual(emails[0].to, 'to1@example.com')
        self.assertEqual(emails[1].to, 'to2@example.com')

    def test_send_without_template(self):
        emails = send('from@a.com', ['to1@example.com', 'to2@example.com'],
                      subject='foo', message='bar', html_message='baz',
                      context={'name': 'Alice'})
        self.assertEqual(len(emails), 2)
        self.assertEqual(emails[0].to, 'to1@example.com')
        self.assertEqual(emails[0].subject, 'foo')
        self.assertEqual(emails[0].message, 'bar')
        self.assertEqual(emails[0].html_message, 'baz')
        self.assertEqual(emails[1].to, 'to2@example.com')

        # Same thing, but now with context
        emails = send('from@a.com', ['to1@example.com'],
                      subject='Hi {{ name }}', message='Message {{ name }}',
                      html_message='<b>{{ name }}</b>',
                      context={'name': 'Bob'})
        self.assertEqual(len(emails), 1)
        self.assertEqual(emails[0].to, 'to1@example.com')
        self.assertEqual(emails[0].subject, 'Hi Bob')
        self.assertEqual(emails[0].message, 'Message Bob')
        self.assertEqual(emails[0].html_message, '<b>Bob</b>')

    def test_send_mail_with_headers(self):
        subject = "subject"
        message = "message"
        from_email = "from@mail.com"
        recipient_list = ['to1@mail.com']
        headers = {'Reply-To':'reply_to@mail.com'}
        emails = send_mail(subject, message, from_email, recipient_list, headers=headers)
        self.assertEqual(len(emails), 1)
        self.assertEqual(emails[0].headers, json.dumps(headers))
