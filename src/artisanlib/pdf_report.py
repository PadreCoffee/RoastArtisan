#
# ABOUT
# PDF versions of the roast, production and ranking reports, drawn with ReportLab.
# Replaces the former QtWebEngine HTML-to-PDF printing (a ~230 MB Chromium) by a small pure-Python
# dependency. The reports take the same values the HTML report templates are filled with, so the
# HTML and PDF variants always show the same data; the row fragments the app already generates for
# the HTML tables are parsed back into cells.

import os
import re
import html
import logging
from html.parser import HTMLParser
from collections.abc import Sequence
from typing import Final, Any, override

_log: Final[logging.Logger] = logging.getLogger(__name__)

FONT: Final[str] = 'RA-Sans'
FONT_BOLD: Final[str] = 'RA-Sans-Bold'

_fonts_registered: bool = False


def available() -> bool:
    try:
        import reportlab  # noqa: F401 # pylint: disable=unused-import
        return True
    except ImportError:
        return False


def _register_fonts() -> None:
    # ReportLab's built-in fonts have no Cyrillic; DejaVu Sans ships with matplotlib already
    global _fonts_registered # pylint: disable=global-statement
    if _fonts_registered:
        return
    import matplotlib as mpl
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    fonts_dir = os.path.join(mpl.get_data_path(), 'fonts', 'ttf')
    pdfmetrics.registerFont(TTFont(FONT, os.path.join(fonts_dir, 'DejaVuSans.ttf')))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, os.path.join(fonts_dir, 'DejaVuSans-Bold.ttf')))
    pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=FONT_BOLD, italic=FONT, boldItalic=FONT_BOLD)
    _fonts_registered = True


def to_markup(fragment:str|None) -> str:
    """HTML fragment from a report value -> ReportLab paragraph markup (keeps <b>, <i>, <br/>)."""
    s = re.sub(r'<br\s*/?>', '\x00', fragment or '')
    s = re.sub(r'<(/?)([bi])>', '\x01\\1\\2\x02', s)
    s = re.sub(r'<[^>]+>', '', s) # drop links, spans, ...
    s = html.escape(html.unescape(s), quote=False)
    s = s.replace('\x00', '<br/>').replace('\x01', '<').replace('\x02', '>')
    return s.strip() or '--'


class _Rows(HTMLParser):
    """Collects the cells of the <tr> fragments the app generates for the HTML report tables."""
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows:list[list[tuple[str, str|None]]] = []
        self._cell:list[str]|None = None
        self._bg:str|None = None

    @override
    def handle_starttag(self, tag:str, attrs:list[tuple[str, str|None]]) -> None:
        if tag == 'tr':
            self.rows.append([])
        elif tag in {'td', 'th'}:
            self._cell = []
            m = re.search(r'background-color:\s*rgba?\(([^)]*)\)', dict(attrs).get('style') or '')
            self._bg = m.group(1) if m else None
        elif tag == 'br' and self._cell is not None:
            self._cell.append('\x00')

    @override
    def handle_endtag(self, tag:str) -> None:
        if tag in {'td', 'th'} and self._cell is not None and self.rows:
            text = html.escape(''.join(self._cell).strip(), quote=False).replace('\x00', '<br/>')
            self.rows[-1].append((text, self._bg))
            self._cell = None

    @override
    def handle_data(self, data:str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def table_rows(fragment:str) -> list[list[tuple[str, str|None]]]:
    """Returns the rows of an HTML table fragment as lists of (cell markup, css background rgba args or None)."""
    p = _Rows()
    p.feed(fragment or '')
    return [r for r in p.rows if r]


def _rgba(args:str) -> Any:
    from reportlab.lib import colors
    parts = [p.strip() for p in args.split(',')]
    rgb = [float(p.rstrip('%')) / 100 if p.endswith('%') else float(p) / 255 for p in parts[:3]]
    return colors.Color(rgb[0], rgb[1], rgb[2])


class _Styles:
    def __init__(self) -> None:
        from reportlab.lib import colors
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
        self.blue = colors.HexColor('#2a6f97')
        self.head = colors.HexColor('#3a8bbf')
        self.grid = colors.HexColor('#d5dadd')
        self.foot = colors.HexColor('#c8cdd0')
        text = colors.HexColor('#0f3d57')
        self.normal = ParagraphStyle('n', fontName=FONT, fontSize=8.5, leading=11, textColor=text)
        self.label = ParagraphStyle('l', parent=self.normal, fontName=FONT_BOLD, alignment=TA_RIGHT)
        self.center = ParagraphStyle('c', parent=self.normal, alignment=TA_CENTER)
        self.title = ParagraphStyle('h', parent=self.normal, fontName=FONT_BOLD, fontSize=18, leading=22,
            textColor=self.blue, alignment=TA_CENTER, spaceAfter=8)
        self.title_left = ParagraphStyle('hl', parent=self.title, alignment=TA_LEFT)
        self.th = ParagraphStyle('th', parent=self.normal, fontName=FONT_BOLD, fontSize=7.5, leading=9,
            textColor=colors.white, alignment=TA_RIGHT)
        self.th_left = ParagraphStyle('thl', parent=self.th, alignment=TA_LEFT)
        self.td = ParagraphStyle('td', parent=self.normal, fontSize=7.5, leading=9, alignment=TA_RIGHT)
        self.td_left = ParagraphStyle('tdl', parent=self.td, alignment=TA_LEFT)


def _doc(pdf_file:str, title:str, letter:bool, landscape:bool) -> Any:
    from reportlab.lib.pagesizes import A4, LETTER, landscape as landscape_page
    from reportlab.lib.units import mm, inch
    from reportlab.platypus import SimpleDocTemplate
    size = LETTER if letter else A4
    margin = 0.7 * inch if letter else 15 * mm
    return SimpleDocTemplate(pdf_file, pagesize=(landscape_page(size) if landscape else size),
        leftMargin=margin, rightMargin=margin, topMargin=margin, bottomMargin=margin, title=title)


def _page_number(canvas:Any, doc:Any) -> None:
    from reportlab.lib import colors
    canvas.saveState()
    canvas.setFont(FONT, 7)
    canvas.setFillColor(colors.grey)
    canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, doc.bottomMargin / 2, str(doc.page))
    canvas.restoreState()


def _image(path:str, width:float, max_height:float|None = None) -> Any:
    from reportlab.platypus import Image
    from reportlab.lib.utils import ImageReader
    w, h = ImageReader(path).getSize()
    height = width * h / w
    if max_height is not None and height > max_height:
        width, height = max_height * w / h, max_height
    return Image(path, width=width, height=height)


def roast_report(pdf_file:str, values:dict[str, Any], graph_png:str|None, flavor_png:str|None, letter:bool = False) -> None:
    """Single roast report. values are the roast-template.htm substitutions; flavor_png only if the cupping is shown."""
    _register_fonts()
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Table, Spacer, PageBreak, KeepTogether
    st = _Styles()
    v = {k: str(x) for k, x in values.items()}
    v['datetime_label'] = v.get('datatime_label', '') # the template spells this label key 'datatime'
    doc = _doc(pdf_file, to_markup(v.get('title')), letter, False)

    def column(keys:list[str]) -> Any:
        rows = [[Paragraph(to_markup(v.get(f'{k}_label')), st.label), Paragraph(to_markup(v.get(k)), st.normal)]
            for k in keys if v.get(f'{k}_label')]
        return Table(rows or [['']], colWidths=[29 * mm, 30 * mm], style=[('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 1.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 1.5)])

    if v.get('cm_label'):
        v['cm'] = v.get('cm_tuple', '')
    story:list[Any] = [
        Paragraph(to_markup(v.get('title')), st.title),
        Table([[column(['datetime', 'beans', 'size', 'weight', 'defects', 'volume', 'density', 'moisture', 'humidity', 'color']),
                column(['charge', 'TP', 'DRY', 'FCs', 'FCe', 'SCs', 'SCe', 'drop', 'cool', 'met', 'ror', 'etbta', 'cm', 'energy', 'CO2']),
                column(['dry_phase', 'mid_phase', 'finish_phase', 'cool_phase', 'background', 'alarms', 'roaster', 'operator', 'organization'])]],
            colWidths=[doc.width / 3] * 3, style=[('VALIGN', (0, 0), (-1, -1), 'TOP')])]
    if v.get('roast_attributes'):
        story.append(Paragraph(to_markup(v['roast_attributes']), st.center))
    if graph_png and os.path.exists(graph_png):
        story += [Spacer(0, 6 * mm), _image(graph_png, doc.width, doc.height * 0.55)]
    events = table_rows(v.get('specialevents', '')) if v.get('show_special_events') != 'none' else []
    if events:
        widths = [9 * mm, 16 * mm, 36 * mm, 7 * mm, 42 * mm, 12 * mm]
        widths.append(max(20 * mm, doc.width - sum(widths)))
        data = [[Paragraph(cell, st.td if i in {2, 4} else st.td_left) for i, (cell, _) in enumerate(row[:7])] for row in events]
        story += [Spacer(0, 4 * mm), Paragraph(f"<b>{to_markup(v.get('specialevents_label'))}</b>", st.center), Spacer(0, 2 * mm),
            Table(data, colWidths=widths[:max(len(r) for r in data)], style=[('LINEBELOW', (0, 0), (-1, -1), 0.25, st.grid),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('LEFTPADDING', (0, 0), (-1, -1), 2), ('RIGHTPADDING', (0, 0), (-1, -1), 2)])]
    for key in ('roasting_notes', 'cupping_notes'):
        if v.get(f'{key}_label'):
            story.append(KeepTogether([Spacer(0, 4 * mm), Paragraph(f'<b>{to_markup(v[f"{key}_label"])}</b>', st.normal),
                Paragraph(to_markup(v.get(key)), st.normal)]))
    if flavor_png and os.path.exists(flavor_png) and v.get('show_cupping') != 'none':
        story += [PageBreak(), _image(flavor_png, doc.width * 0.85, doc.height * 0.9)]
    doc.build(story, onFirstPage=_page_number, onLaterPages=_page_number)


def _table_report(pdf_file:str, title:str, header:list[str], left_columns:set[int], entries:str, footer:list[str],
        widths:Sequence[float], graphs:list[str], letter:bool) -> None:
    _register_fonts()
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Table, Spacer
    st = _Styles()
    doc = _doc(pdf_file, title, letter, True)
    scale = doc.width / sum(widths) # stretch/shrink the relative column widths to the printable width
    data:list[list[Any]] = [[Paragraph(h, st.th_left if i in left_columns else st.th) for i, h in enumerate(header)]]
    style:list[tuple[Any, ...]] = [('BACKGROUND', (0, 0), (-1, 0), st.head), ('GRID', (0, 0), (-1, -1), 0.4, st.grid),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('BACKGROUND', (0, -1), (-1, -1), st.foot),
        ('LEFTPADDING', (0, 0), (-1, -1), 3), ('RIGHTPADDING', (0, 0), (-1, -1), 3)]
    for ri, row in enumerate(table_rows(entries), start=1):
        cells = (row + [('', None)] * len(header))[:len(header)]
        data.append([Paragraph(cell, st.td_left if ci in left_columns else st.td) for ci, (cell, _) in enumerate(cells)])
        style += [('BACKGROUND', (ci, ri), (ci, ri), _rgba(bg)) for ci, (_, bg) in enumerate(cells) if bg]
    data.append([Paragraph(f'<b>{to_markup(f) if f else ""}</b>', st.td_left if i == 0 else st.td) for i, f in enumerate(footer)])
    story:list[Any] = [Paragraph(title, st.title_left), Table(data, colWidths=[w * scale for w in widths], repeatRows=1, style=style)]
    for g in graphs:
        if os.path.exists(g):
            story += [Spacer(0, 5 * mm), _image(g, doc.width, doc.height * 0.9)]
    doc.build(story, onFirstPage=_page_number, onLaterPages=_page_number)


def _with_unit(label:str, unit:str) -> str:
    return f'{to_markup(label)}<br/><font size="6">({to_markup(unit)})</font>'


def production_report(pdf_file:str, values:dict[str, Any], letter:bool = False) -> None:
    """Production report (roast batches). values are the report-template.htm substitutions."""
    v = {k: str(x) for k, x in values.items()}
    u = v.get('unit', '')
    header = [to_markup(v.get('batch')), to_markup(v.get('time')), to_markup(v.get('profile')), to_markup(v.get('beans')),
        _with_unit(v.get('weightin', ''), u), _with_unit(v.get('weightout', ''), u), _with_unit(v.get('loss', ''), '%'),
        _with_unit(v.get('defects', ''), u), _with_unit(v.get('defectsloss', ''), '%')]
    footer = [v.get('sum', ''), '', '', '', v.get('total_in', ''), v.get('total_out', ''), v.get('total_loss', ''),
        v.get('total_defects', ''), v.get('total_defectsloss', '')]
    _table_report(pdf_file, to_markup(v.get('title')), header, {0, 1, 2, 3}, v.get('entries', ''), footer,
        [18, 30, 55, 55, 18, 18, 18, 18, 17], [], letter)


def ranking_report(pdf_file:str, values:dict[str, Any], graphs:list[str], letter:bool = False) -> None:
    """Ranking report. values are the ranking-template.htm substitutions, graphs the PNGs of its two charts."""
    v = {k: str(x) for k, x in values.items()}
    wu, tu = v.get('weight_unit', ''), v.get('temp_unit', '')
    header = ['#', f"{to_markup(v.get('time'))}<br/>{to_markup(v.get('profile'))}", _with_unit(v.get('weightin', ''), wu),
        _with_unit('CHR', tu), _with_unit('FCs', 'min'), _with_unit('FCs', tu), _with_unit('DROP', 'min'), _with_unit('DROP', tu),
        _with_unit('DRY', '%'), _with_unit('MAI', '%'), _with_unit('DEV', '%'), _with_unit('AUC', 'C*min'),
        _with_unit(v.get('weightloss', ''), '%'), to_markup(v.get('colorHeader')), 'Cup', _with_unit('Energy', 'kWh'),
        _with_unit('CO2', 'g'), _with_unit('CO2/kg', 'g')]
    footer = ['AVG', ''] + [v.get(k, '') for k in ('charges_avg', 'charges_temp_avg', 'FCs_time_avg', 'FCs_temp_avg',
        'DROP_time_avg', 'DROP_temp_avg', 'DRY_percent_avg', 'MAI_percent_avg', 'DEV_percent_avg', 'AUC_avg', 'loss_avg',
        'colors_avg', 'cup_avg', 'energy_avg', 'co2_avg', 'co2kg_avg')]
    _table_report(pdf_file, to_markup(v.get('title')), header, {1}, v.get('entries', ''), footer,
        [11, 41] + [12] * 9 + [15, 15, 12, 12, 14, 12, 14], graphs, letter)
