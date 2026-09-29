import unittest

from monitor import extract_image_url_from_html


class SpoilerImageURLTests(unittest.TestCase):
    def test_extracts_og_image(self):
        html = '''
        <html>
          <head>
            <meta property="og:image" content="https://example.com/card.jpg" />
          </head>
          <body>
            <img src="https://example.com/ignored.png" alt="ignored" />
          </body>
        </html>
        '''
        self.assertEqual(extract_image_url_from_html(html), "https://example.com/card.jpg")

    def test_extracts_img_src_when_no_metadata_exists(self):
        html = '''
        <html>
          <body>
            <img src="https://example.com/card-art.png" alt="Card art" />
          </body>
        </html>
        '''
        self.assertEqual(extract_image_url_from_html(html), "https://example.com/card-art.png")


if __name__ == "__main__":
    unittest.main()
