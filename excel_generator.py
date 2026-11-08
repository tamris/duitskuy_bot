import io
import datetime
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

def create_financial_excel_report(wallets: list, transactions: list) -> bytes:
    """
    Menghasilkan file Excel (.xlsx) profesional dengan:
    1. Sheet 'Ringkasan Eksekutif' (KPI Cards, Portofolio Dompet, Analisis Pengeluaran & Pemasukan per Kategori)
    2. Sheet 'Buku Kas Transaksi' (Detail ledger lengkap, auto-filter, zebra-striping, auto-column width, freeze panes)
    """
    wb = openpyxl.Workbook()
    
    # Palette Warna Elegan & Modern
    COLOR_PRIMARY = "1E293B"       # Slate Dark (Header Utama)
    COLOR_HEADER_BG = "334155"     # Slate Medium
    COLOR_ACCENT = "2563EB"        # Royal Blue
    COLOR_GREEN_BG = "DCFCE7"      # Light Green
    COLOR_GREEN_TEXT = "166534"    # Dark Green
    COLOR_RED_BG = "FEE2E2"        # Light Red
    COLOR_RED_TEXT = "991B1B"      # Dark Red
    COLOR_CARD_BG = "F1F5F9"       # Light Slate
    COLOR_ZEBRA = "F8FAFC"         # Ultra Light Slate
    COLOR_BORDER = "CBD5E1"        # Light Gray Border

    font_title = Font(name="Segoe UI", size=16, bold=True, color="0F172A")
    font_subtitle = Font(name="Segoe UI", size=9, italic=True, color="64748B")
    font_section = Font(name="Segoe UI", size=11, bold=True, color="1E293B")
    font_header = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
    font_card_title = Font(name="Segoe UI", size=9, bold=True, color="64748B")
    font_card_val_blue = Font(name="Segoe UI", size=14, bold=True, color="0284C7")
    font_card_val_green = Font(name="Segoe UI", size=14, bold=True, color="16A34A")
    font_card_val_red = Font(name="Segoe UI", size=14, bold=True, color="DC2626")
    font_card_sub = Font(name="Segoe UI", size=8, italic=True, color="64748B")
    font_data = Font(name="Segoe UI", size=10, color="0F172A")
    font_total = Font(name="Segoe UI", size=10, bold=True, color="0F172A")

    thin_border = Border(
        left=Side(style='thin', color=COLOR_BORDER),
        right=Side(style='thin', color=COLOR_BORDER),
        top=Side(style='thin', color=COLOR_BORDER),
        bottom=Side(style='thin', color=COLOR_BORDER)
    )
    
    total_double_border = Border(
        top=Side(style='thin', color=COLOR_BORDER),
        bottom=Side(style='double', color="0F172A")
    )

    header_fill = PatternFill(start_color=COLOR_PRIMARY, end_color=COLOR_PRIMARY, fill_type="solid")
    sub_header_fill = PatternFill(start_color=COLOR_HEADER_BG, end_color=COLOR_HEADER_BG, fill_type="solid")
    card_fill = PatternFill(start_color=COLOR_CARD_BG, end_color=COLOR_CARD_BG, fill_type="solid")
    zebra_fill = PatternFill(start_color=COLOR_ZEBRA, end_color=COLOR_ZEBRA, fill_type="solid")
    green_fill = PatternFill(start_color=COLOR_GREEN_BG, end_color=COLOR_GREEN_BG, fill_type="solid")
    red_fill = PatternFill(start_color=COLOR_RED_BG, end_color=COLOR_RED_BG, fill_type="solid")

    format_currency = '"Rp "#,##0'
    format_percent = '0.0%'

    # Kalkulasi Metrik Finansial
    total_balance = sum(float(w["balance"]) for w in wallets)
    
    total_in = 0.0
    total_out = 0.0
    count_in = 0
    count_out = 0
    cat_out = {}
    cat_in = {}

    for t in transactions:
        amt = float(t["amount"])
        ttype = t["type"]
        cat = t["category"] or "Umum"
        
        if ttype == "IN":
            total_in += amt
            count_in += 1
            cat_in[cat] = cat_in.get(cat, {"count": 0, "amount": 0.0})
            cat_in[cat]["count"] += 1
            cat_in[cat]["amount"] += amt
        else:
            total_out += amt
            count_out += 1
            cat_out[cat] = cat_out.get(cat, {"count": 0, "amount": 0.0})
            cat_out[cat]["count"] += 1
            cat_out[cat]["amount"] += amt

    net_flow = total_in - total_out
    saving_rate = (net_flow / total_in * 100) if total_in > 0 else 0.0

    # =========================================================================
    # SHEET 1: RINGKASAN EKSEKUTIF (DASHBOARD)
    # =========================================================================
    ws1 = wb.active
    ws1.title = "📊 Ringkasan Eksekutif"
    ws1.views.sheetView[0].showGridLines = True

    # Title & Subtitle
    ws1["B2"] = "LAPORAN KEUANGAN PRIBADI"
    ws1["B2"].font = font_title
    
    now_str = datetime.datetime.now().strftime("%d %B %Y, %H:%M WIB")
    ws1["B3"] = f"Dibuat Otomatis oleh Bot Duitku • Tanggal Cetak: {now_str}"
    ws1["B3"].font = font_subtitle

    # Helper Card Painter
    def draw_kpi_card(start_col, title, val_num, val_font, sub_text):
        c1 = f"{start_col}5"
        c2 = f"{chr(ord(start_col)+1)}7"
        ws1.merge_cells(f"{start_col}5:{chr(ord(start_col)+1)}5")
        ws1.merge_cells(f"{start_col}6:{chr(ord(start_col)+1)}6")
        ws1.merge_cells(f"{start_col}7:{chr(ord(start_col)+1)}7")

        ws1[f"{start_col}5"] = title
        ws1[f"{start_col}5"].font = font_card_title
        ws1[f"{start_col}5"].alignment = Alignment(horizontal="center", vertical="center")

        ws1[f"{start_col}6"] = val_num
        ws1[f"{start_col}6"].font = val_font
        ws1[f"{start_col}6"].number_format = format_currency
        ws1[f"{start_col}6"].alignment = Alignment(horizontal="center", vertical="center")

        ws1[f"{start_col}7"] = sub_text
        ws1[f"{start_col}7"].font = font_card_sub
        ws1[f"{start_col}7"].alignment = Alignment(horizontal="center", vertical="center")

        for r in range(5, 8):
            for c in range(ord(start_col) - ord('A') + 1, ord(start_col) - ord('A') + 3):
                cell = ws1.cell(row=r, column=c)
                cell.fill = card_fill
                cell.border = thin_border

    draw_kpi_card("B", "TOTAL SALDO DOMPET", total_balance, font_card_val_blue, f"{len(wallets)} Dompet / Rekening")
    draw_kpi_card("D", "TOTAL PEMASUKAN", total_in, font_card_val_green, f"{count_in} Transaksi Masuk")
    draw_kpi_card("F", "TOTAL PENGELUARAN", total_out, font_card_val_red, f"{count_out} Transaksi Keluar")
    net_font = font_card_val_green if net_flow >= 0 else font_card_val_red
    net_sub = f"Surplus (Saving Rate: {saving_rate:.1f}%)" if net_flow >= 0 else "Defisit Arus Kas"
    draw_kpi_card("H", "ARUS KAS BERSIH (NET FLOW)", net_flow, net_font, net_sub)

    # -------------------------------------------------------------
    # TABEL 1: PORTOFOLIO DOMPET & SALDO (B9)
    # -------------------------------------------------------------
    ws1["B9"] = "1. Portofolio Dompet & Rekening"
    ws1["B9"].font = font_section

    w_headers = ["No", "Nama Akun / Dompet", "Saldo Saat Ini", "Porsi Aset (%)"]
    for i, h in enumerate(w_headers, start=2):
        cell = ws1.cell(row=10, column=i, value=h)
        cell.font = font_header
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    curr_row = 11
    for idx, w in enumerate(wallets, start=1):
        ws1.cell(row=curr_row, column=2, value=idx).alignment = Alignment(horizontal="center")
        ws1.cell(row=curr_row, column=3, value=w["name"]).alignment = Alignment(horizontal="left")
        
        c_bal = ws1.cell(row=curr_row, column=4, value=float(w["balance"]))
        c_bal.number_format = format_currency
        c_bal.alignment = Alignment(horizontal="right")

        portion = (float(w["balance"]) / total_balance) if total_balance > 0 else 0.0
        c_p = ws1.cell(row=curr_row, column=5, value=portion)
        c_p.number_format = format_percent
        c_p.alignment = Alignment(horizontal="right")

        for c in range(2, 6):
            cell = ws1.cell(row=curr_row, column=c)
            cell.font = font_data
            cell.border = thin_border
            if curr_row % 2 == 0:
                cell.fill = zebra_fill
        curr_row += 1

    # Total Row Dompet
    ws1.cell(row=curr_row, column=2, value="")
    ws1.cell(row=curr_row, column=3, value="Total Saldo").font = font_total
    c_tot = ws1.cell(row=curr_row, column=4, value=f"=SUM(D11:D{curr_row-1})")
    c_tot.font = font_total
    c_tot.number_format = format_currency
    c_tot.alignment = Alignment(horizontal="right")
    c_tot_p = ws1.cell(row=curr_row, column=5, value="100.0%")
    c_tot_p.font = font_total
    c_tot_p.alignment = Alignment(horizontal="right")

    for c in range(2, 6):
        ws1.cell(row=curr_row, column=c).border = total_double_border

    # -------------------------------------------------------------
    # TABEL 2: ANALISIS PENGELUARAN PER KATEGORI (G9)
    # -------------------------------------------------------------
    ws1["G9"] = "2. Analisis Pengeluaran per Kategori"
    ws1["G9"].font = font_section

    exp_headers = ["No", "Kategori Pengeluaran", "Frekuensi", "Total Nominal", "Porsi (%)"]
    for i, h in enumerate(exp_headers, start=7):
        cell = ws1.cell(row=10, column=i, value=h)
        cell.font = font_header
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    sorted_out = sorted(cat_out.items(), key=lambda x: x[1]["amount"], reverse=True)
    exp_row = 11
    if not sorted_out:
        ws1.cell(row=exp_row, column=7, value="-").alignment = Alignment(horizontal="center")
        ws1.cell(row=exp_row, column=8, value="Belum ada data pengeluaran")
        ws1.cell(row=exp_row, column=9, value=0)
        ws1.cell(row=exp_row, column=10, value=0).number_format = format_currency
        ws1.cell(row=exp_row, column=11, value=0).number_format = format_percent
        for c in range(7, 12):
            ws1.cell(row=exp_row, column=c).border = thin_border
            ws1.cell(row=exp_row, column=c).font = font_data
        exp_row += 1
    else:
        for idx, (cname, cdata) in enumerate(sorted_out, start=1):
            ws1.cell(row=exp_row, column=7, value=idx).alignment = Alignment(horizontal="center")
            ws1.cell(row=exp_row, column=8, value=cname).alignment = Alignment(horizontal="left")
            ws1.cell(row=exp_row, column=9, value=cdata["count"]).alignment = Alignment(horizontal="center")
            
            c_amt = ws1.cell(row=exp_row, column=10, value=cdata["amount"])
            c_amt.number_format = format_currency
            c_amt.alignment = Alignment(horizontal="right")

            p = (cdata["amount"] / total_out) if total_out > 0 else 0.0
            c_p = ws1.cell(row=exp_row, column=11, value=p)
            c_p.number_format = format_percent
            c_p.alignment = Alignment(horizontal="right")

            for c in range(7, 12):
                cell = ws1.cell(row=exp_row, column=c)
                cell.font = font_data
                cell.border = thin_border
                if exp_row % 2 == 0:
                    cell.fill = zebra_fill
            exp_row += 1

    # Total Row Pengeluaran
    ws1.cell(row=exp_row, column=7, value="")
    ws1.cell(row=exp_row, column=8, value="Total Pengeluaran").font = font_total
    ws1.cell(row=exp_row, column=9, value=count_out).font = font_total
    ws1.cell(row=exp_row, column=9).alignment = Alignment(horizontal="center")
    c_tot_out = ws1.cell(row=exp_row, column=10, value=total_out)
    c_tot_out.font = font_total
    c_tot_out.number_format = format_currency
    c_tot_out.alignment = Alignment(horizontal="right")
    c_tot_out_p = ws1.cell(row=exp_row, column=11, value="100.0%")
    c_tot_out_p.font = font_total
    c_tot_out_p.alignment = Alignment(horizontal="right")

    for c in range(7, 12):
        ws1.cell(row=exp_row, column=c).border = total_double_border

    # -------------------------------------------------------------
    # TABEL 3: ANALISIS PEMASUKAN PER KATEGORI (Di bawah Tabel Dompet)
    # -------------------------------------------------------------
    in_start_row = max(curr_row + 3, 17)
    ws1.cell(row=in_start_row, column=2, value="3. Analisis Pemasukan per Kategori").font = font_section

    in_headers = ["No", "Kategori Pemasukan", "Frekuensi", "Total Nominal", "Porsi (%)"]
    for i, h in enumerate(in_headers, start=2):
        cell = ws1.cell(row=in_start_row+1, column=i, value=h)
        cell.font = font_header
        cell.fill = sub_header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    sorted_in = sorted(cat_in.items(), key=lambda x: x[1]["amount"], reverse=True)
    in_row = in_start_row + 2
    if not sorted_in:
        ws1.cell(row=in_row, column=2, value="-").alignment = Alignment(horizontal="center")
        ws1.cell(row=in_row, column=3, value="Belum ada data pemasukan")
        ws1.cell(row=in_row, column=4, value=0)
        ws1.cell(row=in_row, column=5, value=0).number_format = format_currency
        ws1.cell(row=in_row, column=6, value=0).number_format = format_percent
        for c in range(2, 7):
            ws1.cell(row=in_row, column=c).border = thin_border
            ws1.cell(row=in_row, column=c).font = font_data
        in_row += 1
    else:
        for idx, (cname, cdata) in enumerate(sorted_in, start=1):
            ws1.cell(row=in_row, column=2, value=idx).alignment = Alignment(horizontal="center")
            ws1.cell(row=in_row, column=3, value=cname).alignment = Alignment(horizontal="left")
            ws1.cell(row=in_row, column=4, value=cdata["count"]).alignment = Alignment(horizontal="center")

            c_amt = ws1.cell(row=in_row, column=5, value=cdata["amount"])
            c_amt.number_format = format_currency
            c_amt.alignment = Alignment(horizontal="right")

            p = (cdata["amount"] / total_in) if total_in > 0 else 0.0
            c_p = ws1.cell(row=in_row, column=6, value=p)
            c_p.number_format = format_percent
            c_p.alignment = Alignment(horizontal="right")

            for c in range(2, 7):
                cell = ws1.cell(row=in_row, column=c)
                cell.font = font_data
                cell.border = thin_border
                if in_row % 2 == 0:
                    cell.fill = zebra_fill
            in_row += 1

    # Total Row Pemasukan
    ws1.cell(row=in_row, column=2, value="")
    ws1.cell(row=in_row, column=3, value="Total Pemasukan").font = font_total
    ws1.cell(row=in_row, column=4, value=count_in).font = font_total
    ws1.cell(row=in_row, column=4).alignment = Alignment(horizontal="center")
    c_tot_in = ws1.cell(row=in_row, column=5, value=total_in)
    c_tot_in.font = font_total
    c_tot_in.number_format = format_currency
    c_tot_in.alignment = Alignment(horizontal="right")
    c_tot_in_p = ws1.cell(row=in_row, column=6, value="100.0%")
    c_tot_in_p.font = font_total
    c_tot_in_p.alignment = Alignment(horizontal="right")

    for c in range(2, 7):
        ws1.cell(row=in_row, column=c).border = total_double_border

    # Lebar kolom Sheet 1
    ws1.column_dimensions['A'].width = 3
    ws1.column_dimensions['B'].width = 6
    ws1.column_dimensions['C'].width = 24
    ws1.column_dimensions['D'].width = 22
    ws1.column_dimensions['E'].width = 16
    ws1.column_dimensions['F'].width = 4
    ws1.column_dimensions['G'].width = 6
    ws1.column_dimensions['H'].width = 26
    ws1.column_dimensions['I'].width = 12
    ws1.column_dimensions['J'].width = 22
    ws1.column_dimensions['K'].width = 14

    # =========================================================================
    # SHEET 2: BUKU KAS TRANSAKSI (DETAIL LEDGER)
    # =========================================================================
    ws2 = wb.create_sheet(title="📝 Buku Kas Transaksi")
    ws2.views.sheetView[0].showGridLines = True

    # Title Sheet 2
    ws2["A1"] = "BUKU KAS & CATATAN TRANSAKSI DETAIL"
    ws2["A1"].font = font_title
    ws2["A2"] = f"Total {len(transactions)} Transaksi Tercatat • Data terurut dari yang paling awal hingga terbaru"
    ws2["A2"].font = font_subtitle

    headers_tx = [
        "No", 
        "Tanggal & Waktu", 
        "Dompet / Akun", 
        "Tipe", 
        "Kategori", 
        "Keterangan / Deskripsi", 
        "Nominal (Rp)"
    ]

    for col_idx, h in enumerate(headers_tx, start=1):
        cell = ws2.cell(row=4, column=col_idx, value=h)
        cell.font = font_header
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border
    ws2.row_dimensions[4].height = 25

    tx_row = 5
    for idx, t in enumerate(transactions, start=1):
        is_in = t["type"] == "IN"
        tipe_label = "Pemasukan 🟢" if is_in else "Pengeluaran 🔴"
        
        c_no = ws2.cell(row=tx_row, column=1, value=idx)
        c_no.alignment = Alignment(horizontal="center")

        # Parse date jika bisa
        raw_date = str(t.get("date", ""))
        c_date = ws2.cell(row=tx_row, column=2, value=raw_date)
        c_date.alignment = Alignment(horizontal="center")

        c_w = ws2.cell(row=tx_row, column=3, value=t.get("wallet_name") or "Cash")
        c_w.alignment = Alignment(horizontal="center")

        c_type = ws2.cell(row=tx_row, column=4, value=tipe_label)
        c_type.alignment = Alignment(horizontal="center")
        c_type.fill = green_fill if is_in else red_fill
        c_type.font = Font(name="Segoe UI", size=9, bold=True, color=COLOR_GREEN_TEXT if is_in else COLOR_RED_TEXT)

        c_cat = ws2.cell(row=tx_row, column=5, value=t.get("category") or "Umum")
        c_cat.alignment = Alignment(horizontal="left")

        c_desc = ws2.cell(row=tx_row, column=6, value=t.get("description") or "-")
        c_desc.alignment = Alignment(horizontal="left")

        c_amt = ws2.cell(row=tx_row, column=7, value=float(t["amount"]))
        c_amt.number_format = format_currency
        c_amt.alignment = Alignment(horizontal="right")
        amt_font = Font(name="Segoe UI", size=10, bold=True, color=COLOR_GREEN_TEXT if is_in else COLOR_RED_TEXT)
        c_amt.font = amt_font

        for col_idx in range(1, 8):
            cell = ws2.cell(row=tx_row, column=col_idx)
            cell.border = thin_border
            if col_idx != 4 and col_idx != 7:  # Jangan timpa warna hijau/merah di tipe & nominal
                cell.font = font_data
                if tx_row % 2 == 0:
                    cell.fill = zebra_fill
            elif col_idx == 7 and tx_row % 2 == 0:
                cell.fill = zebra_fill
        
        ws2.row_dimensions[tx_row].height = 20
        tx_row += 1

    # Baris Summary di bagian bawah Buku Kas
    ws2.cell(row=tx_row, column=1, value="")
    ws2.cell(row=tx_row, column=2, value="Grand Total").font = font_total
    ws2.cell(row=tx_row, column=3, value="")
    ws2.cell(row=tx_row, column=4, value="")
    ws2.cell(row=tx_row, column=5, value="")
    ws2.cell(row=tx_row, column=6, value=f"{len(transactions)} Transaksi").font = font_total
    
    if transactions:
        c_sum = ws2.cell(row=tx_row, column=7, value=f"=SUM(G5:G{tx_row-1})")
    else:
        c_sum = ws2.cell(row=tx_row, column=7, value=0)
    c_sum.font = font_total
    c_sum.number_format = format_currency
    c_sum.alignment = Alignment(horizontal="right")

    for col_idx in range(1, 8):
        ws2.cell(row=tx_row, column=col_idx).border = total_double_border
    ws2.row_dimensions[tx_row].height = 22

    # Auto-filter & Freeze Panes pada Sheet 2
    ws2.auto_filter.ref = f"A4:G{tx_row}"
    ws2.freeze_panes = "A5"

    # Auto-fit column width pada Sheet 2
    col_widths = {
        1: 6,   # No
        2: 20,  # Tanggal
        3: 16,  # Dompet
        4: 18,  # Tipe
        5: 24,  # Kategori
        6: 35,  # Keterangan
        7: 22   # Nominal
    }
    for col_idx, width in col_widths.items():
        ws2.column_dimensions[get_column_letter(col_idx)].width = width

    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()
