from django.test import TestCase


class DefaultLanguageTests(TestCase):
    def test_english_browser_still_opens_in_azerbaijani(self):
        response = self.client.get("/login/", HTTP_ACCEPT_LANGUAGE="en")
        html = response.content.decode()
        self.assertContains(response, "Xoş gəlmisiniz")
        self.assertNotContains(response, "Sign in")
        self.assertLess(html.find('value="az"'), html.find('value="en"'))
        self.assertIn('value="az" selected', html)

    def test_explicit_language_choice_is_kept(self):
        self.client.cookies["django_language"] = "en"
        response = self.client.get("/login/", HTTP_ACCEPT_LANGUAGE="az")
        self.assertContains(response, "Sign in")
        self.assertIn('value="en" selected', response.content.decode())
