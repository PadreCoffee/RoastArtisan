"""PDF reports are drawn with ReportLab (artisanlib.pdf_report) instead of printing the HTML
reports through QtWebEngine. They are fed the same values as the HTML report templates."""

import os
import re
from pathlib import Path

from matplotlib.figure import Figure

from artisanlib import pdf_report


def _pages(pdf:Path) -> int:
    return len(re.findall(rb'/Type /Page[^s]', pdf.read_bytes()))


def _png(path:Path) -> str:
    fig = Figure(figsize=(6, 3))
    fig.add_subplot(111).plot([0, 1, 2], [3, 1, 2])
    fig.savefig(path, dpi=50)
    return str(path)


def test_reportlab_is_available() -> None:
    assert pdf_report.available()


def test_markup_keeps_bold_and_breaks_and_drops_links() -> None:
    assert pdf_report.to_markup('<a href="x">BT 441&deg;F</a><br>ET <b>414F</b>') == 'BT 441°F<br/>ET <b>414F</b>'
    assert pdf_report.to_markup('a < b & c') == 'a &lt; b &amp; c'
    assert pdf_report.to_markup('') == '--'


def test_table_rows_extracts_cells_and_background() -> None:
    rows = pdf_report.table_rows('<tr><td style="background-color: rgba(10%,20%,30%,1)"></td>'
        '<td>23.10.2026<br><a href="u">Уганда &amp; Кения</a></td></tr><tr><td>2</td></tr>')
    assert rows[0][0] == ('', '10%,20%,30%,1')
    assert rows[0][1] == ('23.10.2026<br/>Уганда &amp; Кения', None)
    assert rows[1] == [('2', None)]


def test_roast_report_pdf(tmp_path:Path) -> None:
    values = {'title': 'СТМ ПЧК Уганда Элгон', 'datatime_label': 'Дата', 'datetime': 'Fri Oct 23 2026',
        'beans_label': 'Зёрна', 'beans': '<a href="x">Уганда</a>', 'charge_label': 'Загрузка', 'charge': 'BT 441&deg;F <br>ET 414F',
        'roaster_label': 'Ростер', 'roaster': 'Probat P12III', 'show_special_events': 'inline', 'specialevents_label': 'События',
        'specialevents': ''.join(f"<tr><td>{i}</td><td>0{i}:00</td><td align='right'>300F / 400F</td><td></td>"
                                 f"<td align='right'> -- </td><td></td><td>(Горелка {i}0)</td></tr>" for i in range(1, 60)),
        'roasting_notes_label': 'Заметки', 'roasting_notes': 'ровно<br>без дефектов', 'show_cupping': 'none'}
    pdf = tmp_path / 'roast.pdf'
    pdf_report.roast_report(str(pdf), values, _png(tmp_path / 'graph.png'), None)
    assert pdf.read_bytes().startswith(b'%PDF-')
    assert _pages(pdf) >= 2 # the long event list flows onto a second page


def test_production_and_ranking_report_pdf(tmp_path:Path) -> None:
    row = '<tr><td>R1</td><td>23.10.2026 15:59</td><td>Уганда</td><td>Уганда</td><td>24.251</td><td>20.1</td><td>17.1</td><td>0</td><td>0</td></tr>'
    production = tmp_path / 'production.pdf'
    pdf_report.production_report(str(production), {'title': 'Батчи обжарки', 'entries': row * 3, 'unit': 'kg', 'sum': 'Сумма',
        'total_in': '72.75', 'batch': 'Батч', 'time': 'Дата', 'profile': 'Название', 'beans': 'Зёрна'}, letter=True)
    assert production.read_bytes().startswith(b'%PDF-')
    ranking_row = ('<tr><td style="background-color: rgba(12%,47%,71%,1)"></td><td>23.10.2026<br>Уганда</td>'
        + '<td>1.0</td>' * 16 + '</tr>')
    ranking = tmp_path / 'ranking.pdf'
    graphs = [_png(tmp_path / 'r1.png'), _png(tmp_path / 'r2.png'), str(tmp_path / 'missing.png')]
    pdf_report.ranking_report(str(ranking), {'title': 'Рейтинг обжарки', 'entries': ranking_row * 2, 'charges_avg': '24.25'}, graphs)
    assert ranking.read_bytes().startswith(b'%PDF-')
    assert os.path.getsize(ranking) > os.path.getsize(production)
