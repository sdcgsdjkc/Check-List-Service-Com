DARK = {
    "window_top": "#0e1219",
    "window_bottom": "#191f2b",
    "text": "#e6ebf2",
    "glass": "#1a2130",
    "glass_strong": "#232c3d",
    "glass_border": "rgba(255,255,255,0.08)",
    "header_bg": "#161c27",
    "logo_bg": "#ffffff",
    "brand": "#ff6b6b",
    "brand_sub": "#8a93a0",
    "spec_label": "#8a93a0",
    "spec_value": "#ffffff",
    "hint_bg": "#2a1a1c",
    "hint_border": "rgba(255,90,95,0.35)",
    "hint_text": "#ffb3b5",
    "status_label": "#9aa4b0",
    "dev": "#5a6472",
    "btn_bg": "#232c3b",
    "btn_border": "rgba(255,255,255,0.10)",
    "btn_hover": "#2c374a",
    "accent": "#ff5a5f",
    "pass_bg": "#2e9e46",
    "pass_border": "#3bbb57",
    "skip_bg": "#394354",
    "list_bg": "#141a24",
    "list_border": "rgba(255,255,255,0.05)",
    "list_sel_bg": "#e8484d",
    "list_sel_text": "#ffffff",
    "input_bg": "#10151d",
    "input_border": "rgba(255,255,255,0.09)",
    "progress_bg": "#10151d",
    "report_bg": "#141a24",
    "report_border": "rgba(255,255,255,0.08)",
    "report_rule": "rgba(255,255,255,0.08)",
    "report_text": "#e6ebf2",
    "report_muted": "#8a93a0",
    "report_num": "#5a6472",
    "pass": "#57c06a",
    "skip": "#e0b13a",
    "fail": "#ff5f5f",
    "notrun": "#6b7480",
}

LIGHT = {
    "window_top": "#f4f7fc",
    "window_bottom": "#e0e8f1",
    "text": "#1b2230",
    "glass": "#ffffff",
    "glass_strong": "#eef2f8",
    "glass_border": "rgba(0,0,0,0.07)",
    "header_bg": "#ffffff",
    "logo_bg": "#ffffff",
    "brand": "#e23b3b",
    "brand_sub": "#7a838f",
    "spec_label": "#5c6572",
    "spec_value": "#141a24",
    "hint_bg": "#fdecec",
    "hint_border": "rgba(226,59,59,0.28)",
    "hint_text": "#9a2f2b",
    "status_label": "#5c6572",
    "dev": "#9aa3b0",
    "btn_bg": "#eef2f8",
    "btn_border": "rgba(0,0,0,0.10)",
    "btn_hover": "#e2e9f2",
    "accent": "#e23b3b",
    "pass_bg": "#2e9e46",
    "pass_border": "#37b854",
    "skip_bg": "#e6ebf1",
    "list_bg": "#f6f9fc",
    "list_border": "rgba(0,0,0,0.05)",
    "list_sel_bg": "#e23b3b",
    "list_sel_text": "#ffffff",
    "input_bg": "#f6f9fc",
    "input_border": "rgba(0,0,0,0.12)",
    "progress_bg": "#e6ebf1",
    "report_bg": "#ffffff",
    "report_border": "rgba(0,0,0,0.08)",
    "report_rule": "rgba(0,0,0,0.08)",
    "report_text": "#1b2230",
    "report_muted": "#5c6572",
    "report_num": "#9aa3b0",
    "pass": "#2e9e46",
    "skip": "#b8791f",
    "fail": "#d23a3a",
    "notrun": "#9aa3b0",
}

THEMES = {"dark": DARK, "light": LIGHT}


def colors(name):
    return THEMES.get(name, DARK)


def stylesheet(name):
    c = colors(name)
    return f"""
* {{ font-family: 'Segoe UI', 'Segoe UI Variable', Arial, sans-serif; }}
QMainWindow {{ background: {c['window_bottom']}; }}
#root {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {c['window_top']}, stop:1 {c['window_bottom']}); }}
QWidget {{ background: transparent; color: {c['text']}; font-size: 13px; }}
#header {{ background: {c['header_bg']}; border: 1px solid {c['glass_border']};
          border-radius: 18px; }}
#logoLabel {{ background: {c['logo_bg']}; border-radius: 12px; padding: 5px 12px; }}
#brandLabel {{ font-size: 21px; font-weight: 800; color: {c['brand']}; }}
#brandSub {{ color: {c['brand_sub']}; font-size: 11px; }}
#specLabel {{ color: {c['spec_label']}; font-size: 12px; }}
#specValue {{ color: {c['spec_value']}; font-weight: 600; font-size: 12px; }}
#contentCard {{ background: {c['glass']}; border: 1px solid {c['glass_border']};
               border-radius: 18px; }}
#hintLabel {{ background: {c['hint_bg']}; border: 1px solid {c['hint_border']};
             border-radius: 12px; padding: 12px 16px; color: {c['hint_text']}; font-size: 14px; }}
#statusLabel {{ color: {c['status_label']}; font-weight: 600; }}
#devLabel {{ color: {c['dev']}; font-size: 11px; }}
#bigValue {{ font-size: 17px; font-weight: 700; padding: 6px; }}
#themeButton {{ font-size: 18px; padding: 6px 12px; min-width: 20px; border-radius: 12px; }}
QPushButton {{ background: {c['btn_bg']}; border: 1px solid {c['btn_border']};
              border-radius: 12px; padding: 9px 20px; }}
QPushButton:hover {{ background: {c['btn_hover']}; }}
QPushButton:pressed {{ background: {c['accent']}; color: #ffffff; }}
#passButton {{ background: {c['pass_bg']}; border: 1px solid {c['pass_border']};
              font-weight: 700; color: #ffffff; }}
#passButton:hover {{ background: {c['pass_border']}; }}
#skipButton {{ background: {c['skip_bg']}; }}
#failButton {{ background: transparent; border: 1px solid {c['fail']}; color: {c['fail']};
              font-weight: 700; }}
#failButton:hover {{ background: {c['fail']}; color: #ffffff; }}
#ghostButton {{ background: transparent; border: 1px solid {c['btn_border']};
               color: {c['status_label']}; }}
#ghostButton:hover {{ background: {c['btn_hover']}; }}
QListWidget {{ background: {c['list_bg']}; border: 1px solid {c['list_border']};
              border-radius: 16px; outline: none; padding: 6px; }}
QListWidget::item {{ padding: 11px 10px; border-radius: 10px; margin: 2px 2px; }}
QListWidget::item:selected {{ background: {c['list_sel_bg']}; color: {c['list_sel_text']}; }}
QListWidget::item:hover {{ background: {c['glass_strong']}; }}
QLineEdit, QTextEdit {{ background: {c['input_bg']}; border: 1px solid {c['input_border']};
                       border-radius: 12px; padding: 8px 10px;
                       selection-background-color: {c['accent']}; }}
QProgressBar {{ background: {c['progress_bg']}; border: 1px solid {c['input_border']};
               border-radius: 9px; height: 18px; text-align: center; }}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 8px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['glass_strong']}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QMessageBox {{ background: {c['window_bottom']}; }}
QMessageBox QLabel {{ color: {c['text']}; }}
"""


STYLESHEET = stylesheet("dark")
