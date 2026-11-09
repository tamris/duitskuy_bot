import unittest
import os
import io
import csv
from database import init_db, get_db_connection
import models
from handlers import parse_quick_entry, parse_amount

class TestFinanceBot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import database
        cls.orig_db = database.DB_PATH
        database.DB_PATH = os.path.join(os.path.dirname(__file__), "test_finance.db")
        init_db()

    @classmethod
    def tearDownClass(cls):
        import database
        database.DB_PATH = cls.orig_db
        test_db = os.path.join(os.path.dirname(__file__), "test_finance.db")
        if os.path.exists(test_db):
            try:
                os.remove(test_db)
            except Exception:
                pass

    def setUp(self):
        # Reset data transaksi
        conn = get_db_connection()
        conn.execute("DELETE FROM transactions;")
        conn.execute("UPDATE wallets SET balance = 0;")
        conn.commit()
        conn.close()

    def test_amount_parsing(self):
        self.assertEqual(parse_amount("25000"), 25000.0)
        self.assertEqual(parse_amount("25.000"), 25000.0)
        self.assertEqual(parse_amount("25k"), 25000.0)
        self.assertEqual(parse_amount("25rb"), 25000.0)
        self.assertEqual(parse_amount("1.5jt"), 1500000.0)
        self.assertEqual(parse_amount("1,5jt"), 1500000.0)
        self.assertEqual(parse_amount("500000"), 500000.0)
        self.assertEqual(parse_amount("500k"), 500000.0)

    def test_quick_entry_parsing(self):
        # Pengeluaran
        res = parse_quick_entry("-25000 kopi")
        self.assertIsNotNone(res)
        tx_type, amount, desc = res
        self.assertEqual(tx_type, "OUT")
        self.assertEqual(amount, 25000.0)
        self.assertEqual(desc, "kopi")

        # Pemasukan
        res2 = parse_quick_entry("+1500000 gaji bulanan")
        self.assertIsNotNone(res2)
        tx_type2, amount2, desc2 = res2
        self.assertEqual(tx_type2, "IN")
        self.assertEqual(amount2, 1500000.0)
        self.assertEqual(desc2, "gaji bulanan")

        # Format ribuan & spasi
        res3 = parse_quick_entry("- 15.000 parkir motor")
        self.assertIsNotNone(res3)
        self.assertEqual(res3, ("OUT", 15000.0, "parkir motor"))

        # Format k suffix
        res4 = parse_quick_entry("-25k kopi susu")
        self.assertIsNotNone(res4)
        self.assertEqual(res4, ("OUT", 25000.0, "kopi susu"))

        # Format tanpa minus '-' (Otomatis Pengeluaran!)
        res5 = parse_quick_entry("Kopi susu 25k")
        self.assertIsNotNone(res5)
        self.assertEqual(res5, ("OUT", 25000.0, "Kopi susu"))

        res6 = parse_quick_entry("makan siang 35.000")
        self.assertIsNotNone(res6)
        self.assertEqual(res6, ("OUT", 35000.0, "makan siang"))

        res7 = parse_quick_entry("25k kopi susu")
        self.assertIsNotNone(res7)
        self.assertEqual(res7, ("OUT", 25000.0, "kopi susu"))

        res8 = parse_quick_entry("bensin 50rb jago")
        self.assertIsNotNone(res8)
        self.assertEqual(res8, ("OUT", 50000.0, "bensin jago"))

    def test_category_detection(self):
        self.assertEqual(models.detect_category("kopi starbucks", "OUT"), "Makanan & Minuman")
        self.assertEqual(models.detect_category("bensin pertalite", "OUT"), "Transportasi")
        self.assertEqual(models.detect_category("belanja sabun dan beras di indomaret", "OUT"), "Belanja Bulanan")
        self.assertEqual(models.detect_category("tagihan listrik pln", "OUT"), "Utilitas & Tagihan")
        self.assertEqual(models.detect_category("wifi indihome", "OUT"), "Utilitas & Tagihan")
        self.assertEqual(models.detect_category("tagihan paylater", "OUT"), "Cicilan & Hutang")
        self.assertEqual(models.detect_category("tagihan kartu kredit", "OUT"), "Cicilan & Hutang")
        self.assertEqual(models.detect_category("cicilan spaylater", "OUT"), "Cicilan & Hutang")
        self.assertEqual(models.detect_category("bayar kredivo", "OUT"), "Cicilan & Hutang")
        self.assertEqual(models.detect_category("angsuran leasing motor", "OUT"), "Cicilan & Hutang")
        self.assertEqual(models.detect_category("gaji bulanan", "IN"), "Gaji")
        self.assertEqual(models.detect_category("bonus akhir tahun", "IN"), "Bonus & Hadiah")

    def test_transactions_and_wallet_balance(self):
        wallet = models.get_default_wallet()
        self.assertEqual(wallet["balance"], 0.0)

        # 1. Tambah Pemasukan
        tx_in = models.add_transaction(
            wallet_id=wallet["id"],
            tx_type="IN",
            amount=5000000,
            category="Gaji",
            description="Gaji Masuk"
        )
        self.assertEqual(tx_in["new_balance"], 5000000.0)

        # 2. Tambah Pengeluaran
        tx_out = models.add_transaction(
            wallet_id=wallet["id"],
            tx_type="OUT",
            amount=50000,
            category="Makanan & Minuman",
            description="Makan Siang"
        )
        self.assertEqual(tx_out["new_balance"], 4950000.0)

        # 3. Cek Rekap
        rekap = models.get_monthly_rekap()
        self.assertEqual(rekap["total_in"], 5000000.0)
        self.assertEqual(rekap["total_out"], 50000.0)
        self.assertEqual(rekap["net_flow"], 4950000.0)
        self.assertEqual(rekap["count_in"], 1)
        self.assertEqual(rekap["count_out"], 1)

        # 4. Cek Format Rupiah
        self.assertEqual(models.format_rupiah(50000), "Rp 50.000")
        self.assertEqual(models.format_rupiah(5000000), "Rp 5.000.000")

    def test_export_data(self):
        wallet = models.get_default_wallet()
        models.add_transaction(wallet["id"], "IN", 100000, "Bonus", "Bonus 1")
        models.add_transaction(wallet["id"], "OUT", 20000, "Transportasi", "Bensin")

        rows = models.get_all_transactions_for_export()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["category"], "Bonus")
        self.assertEqual(rows[1]["category"], "Transportasi")

        # Test Excel Report Generator
        from excel_generator import create_financial_excel_report
        wallets = models.get_all_wallets()
        xlsx_bytes = create_financial_excel_report(wallets, rows)
        self.assertTrue(len(xlsx_bytes) > 1000)
        self.assertTrue(xlsx_bytes.startswith(b"PK")) # Valid ZIP / XLSX signature

    def test_wallet_aliases_and_management(self):
        # 1. Tambah dompet baru via alias gpy
        w = models.add_wallet("gpy", 50000)
        self.assertIsNotNone(w)
        self.assertEqual(w["name"], "Gopay")
        self.assertEqual(w["balance"], 50000.0)

        # 2. Cek pencarian via alias gpy
        found = models.get_wallet_by_name("gpy")
        self.assertIsNotNone(found)
        self.assertEqual(found["name"], "Gopay")

        # 3. Cek ekstraksi teks dengan alias
        w_res, clean_desc = models.extract_wallet_from_text("kopi gpy")
        self.assertEqual(w_res["name"], "Gopay")
        self.assertEqual(clean_desc, "kopi")

        # 4. Set saldo
        models.set_wallet_balance(w["id"], 75000)
        updated = models.get_wallet_by_name("Gopay")
        self.assertEqual(updated["balance"], 75000.0)

        # 5. Hapus dompet
        self.assertTrue(models.delete_wallet(w["id"]))
        self.assertIsNone(models.get_wallet_by_name("Gopay"))

    def test_api_key_management(self):
        # 1. Masking
        self.assertEqual(models.mask_api_key("AIzaSyB1234567890abcdef"), "AIzaSy...cdef")
        
        # 2. Add key
        new_k = models.add_api_key("AIzaSyTestKey1234567890", label="Test Key 1")
        self.assertIsNotNone(new_k)
        self.assertEqual(new_k["label"], "Test Key 1")
        
        # 3. Get keys
        all_keys = models.get_all_api_keys()
        self.assertTrue(any(k["id"] == new_k["id"] for k in all_keys))
        
        # 4. Record usage
        models.record_api_key_usage(new_k["id"], success=False)
        k_failed = models.get_api_key_by_id(new_k["id"])
        self.assertEqual(k_failed["fail_count"], 1)
        
        models.record_api_key_usage(new_k["id"], success=True)
        k_success = models.get_api_key_by_id(new_k["id"])
        self.assertEqual(k_success["fail_count"], 0)
        
        # 5. Delete key
        self.assertTrue(models.delete_api_key(new_k["id"]))
        self.assertIsNone(models.get_api_key_by_id(new_k["id"]))

    def test_database_reset(self):
        w = models.get_default_wallet()
        models.add_transaction(w["id"], "IN", 500000, "Bonus", "Bonus Reset Test")
        res = models.reset_database(preserve_api_keys=True)
        self.assertTrue(res["api_keys_preserved"])
        self.assertEqual(len(models.get_all_transactions_for_export()), 0)
        wallets = models.get_all_wallets()
        self.assertEqual(sum(item["balance"] for item in wallets), 0.0)

    def test_toggle_transaction_type(self):
        w = models.get_default_wallet()
        tx = models.add_transaction(w["id"], "OUT", 50000, "Makanan & Minuman", "Kopi Susu")
        w_cur = models.get_wallet_by_id(w["id"])
        self.assertEqual(w_cur["balance"], -50000.0)

        # Toggle OUT -> IN
        res = models.toggle_transaction_type(tx["id"])
        self.assertIsNotNone(res)
        self.assertEqual(res["new_type"], "IN")
        self.assertEqual(res["new_balance"], 50000.0)

        # Toggle IN -> OUT
        res2 = models.toggle_transaction_type(tx["id"])
        self.assertIsNotNone(res2)
        self.assertEqual(res2["new_type"], "OUT")
        self.assertEqual(res2["new_balance"], -50000.0)

    def test_whitelist_middleware(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        from middlewares import WhitelistMiddleware, get_allowed_telegram_ids

        # 1. Test get_allowed_telegram_ids
        os.environ["ALLOWED_TELEGRAM_IDS"] = "12345, 67890"
        ids = get_allowed_telegram_ids()
        self.assertEqual(ids, {12345, 67890})

        # 2. Test WhitelistMiddleware with allowed user
        mw = WhitelistMiddleware(allowed_user_ids={12345})
        mock_handler = AsyncMock(return_value="OK")
        mock_event = MagicMock()
        mock_event.from_user.id = 12345
        mock_event.text = "halo"

        res = asyncio.run(mw(mock_handler, mock_event, {}))
        self.assertEqual(res, "OK")
        mock_handler.assert_called_once()

        # 3. Test WhitelistMiddleware with unauthorized user
        mock_handler.reset_mock()
        mock_event_unauth = MagicMock()
        mock_event_unauth.from_user.id = 99999
        mock_event_unauth.from_user.username = "intruder"
        mock_event_unauth.text = "halo"
        mock_event_unauth.reply = AsyncMock()

        res_unauth = asyncio.run(mw(mock_handler, mock_event_unauth, {}))
        self.assertIsNone(res_unauth)
        mock_handler.assert_not_called()
        mock_event_unauth.reply.assert_called_once()
        self.assertIn("Akses Ditolak", mock_event_unauth.reply.call_args[0][0])

        # 4. Test /id command works even for unauthorized user
        mock_event_id = MagicMock()
        mock_event_id.from_user.id = 99999
        mock_event_id.text = "/id"
        mock_event_id.reply = AsyncMock()

        res_id = asyncio.run(mw(mock_handler, mock_event_id, {}))
        self.assertIsNone(res_id)
        mock_handler.assert_not_called()
        mock_event_id.reply.assert_called_once()
        self.assertIn("ID Telegram Anda", mock_event_id.reply.call_args[0][0])

if __name__ == "__main__":
    unittest.main()

