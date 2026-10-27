import unittest
from scanner import candidate

class ScannerTests(unittest.TestCase):
    def test_missing_pairs(self):
        self.assertIsNone(candidate("solana","abc",[]))
    def test_wrong_token(self):
        self.assertIsNone(candidate("solana","abc",[{"chainId":"solana","baseToken":{"address":"xyz"}}]))

if __name__ == "__main__":
    unittest.main()
