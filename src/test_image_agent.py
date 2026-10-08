import unittest
from pathlib import Path

from image_agent import conversational_intent, edit_request, select_image


class ImageRoutingTests(unittest.TestCase):
    def setUp(self):
        self.images = [Path(r"C:\images\latest.png"), Path(r"C:\images\older.jpg")]

    def test_edit_intent_with_last_image(self):
        prompt, targets = edit_request("编辑上一张，把背景改成夜景", self.images)
        self.assertEqual(prompt, "把背景改成夜景")
        self.assertEqual(targets, [self.images[0]])

    def test_number_selects_displayed_image(self):
        self.assertEqual(select_image("第 2 张", self.images), self.images[1])

    def test_filename_selects_matching_image(self):
        prompt, targets = edit_request("修改 older.jpg，让它变成黑白风格", self.images)
        self.assertEqual(targets, [self.images[1]])
        self.assertIn("older.jpg", prompt)

    def test_ambiguous_edit_does_not_guess(self):
        prompt, targets = edit_request("把图片改成夜景", self.images)
        self.assertIsNone(targets)
        self.assertTrue(prompt)

    def test_natural_language_generation_and_edit(self):
        self.assertEqual(conversational_intent("生成一张太空站概念图")[0], "generate")
        self.assertEqual(conversational_intent("把上一张改成水彩画")[0], "edit")


if __name__ == "__main__":
    unittest.main()
