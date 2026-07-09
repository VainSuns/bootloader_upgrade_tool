"""Static style constants for Phase 11 GUI layout skeleton.

This file intentionally contains only visual/layout constants.  Do not add
transport, protocol, hardware, flash, metadata, or operation-library logic here.
"""

WINDOW_TITLE = "DSP28377D Bootloader Upgrade Tool"
WINDOW_DEFAULT_SIZE = (1440, 900)
WINDOW_MINIMUM_SIZE = (1280, 760)

TITLE_TAB_ROW_HEIGHT = 38
RIBBON_CONTENT_ROW_HEIGHT = 112
TOP_RIBBON_TOTAL_HEIGHT = TITLE_TAB_ROW_HEIGHT + RIBBON_CONTENT_ROW_HEIGHT

NAVIGATION_WIDTH = 240
NAVIGATION_MIN_WIDTH = 220
NAVIGATION_MAX_WIDTH = 280

BOTTOM_DOCK_EXPANDED_HEIGHT = 160
BOTTOM_DOCK_COLLAPSED_HEIGHT = 30
LOG_DETAIL_DEFAULT_HEIGHT = 200
MEMORY_CONTROL_BAR_HEIGHT = 48
MEMORY_DEFAULT_ROWS = 100
MEMORY_WORD_COLUMNS = 16

PAGE_CONTENT_MAX_WIDTH = 1100

ADVANCED_TAB_MIN_WIDTH = 900
ADVANCED_RAM_TAB_MIN_WIDTH = 900
ADVANCED_TWO_COLUMN_MIN_WIDTH = 420
ADVANCED_TABS_MIN_HEIGHT = 260
ADVANCED_RESULT_MIN_HEIGHT = 140

PROGRAM_PAGE_MIN_WIDTH = 860
PROGRAM_APP_CARD_MIN_HEIGHT = 150
PROGRAM_STATUS_CARD_MIN_HEIGHT = 150
PROGRAM_RESULT_CARD_MIN_HEIGHT = 220

SETTINGS_PAGE_MIN_WIDTH = 860

APP_QSS = r"""
QMainWindow {
    background: #f5f7fb;
}

QFrame#topRibbonShell {
    background: #ffffff;
    border-bottom: 1px solid #d5d9e2;
}

QFrame#titleTabRow {
    background: #f7f9fc;
    border-bottom: 1px solid #dfe3ea;
}

QLabel#appTitleLabel {
    font-size: 16px;
    font-weight: 600;
    color: #263445;
    padding-left: 14px;
}

QPushButton.ribbonTabButton {
    border: none;
    padding: 8px 16px;
    color: #36465a;
    background: transparent;
    font-weight: 500;
}

QPushButton.ribbonTabButton:checked {
    background: #ffffff;
    border-left: 1px solid #dfe3ea;
    border-right: 1px solid #dfe3ea;
    border-top: 2px solid #2f6fed;
    color: #173f8a;
}

QFrame#ribbonContentRow {
    background: #ffffff;
}

QFrame.ribbonGroup {
    background: #ffffff;
    border-right: 1px solid #e2e6ee;
    margin: 0px;
}

QLabel.ribbonGroupCaption {
    color: #697789;
    font-size: 11px;
    padding-bottom: 1px;
}

QToolButton.ribbonToolButton {
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 4px 6px;
    min-width: 64px;
    color: #263445;
}

QToolButton.ribbonToolButton:hover {
    background: #edf4ff;
    border: 1px solid #c7dafb;
}

QFrame#navigationPanel {
    background: #ffffff;
    border-right: 1px solid #d5d9e2;
}

QTreeWidget#navigationTree {
    border: none;
    background: #ffffff;
    outline: none;
    font-size: 13px;
}

QTreeWidget#navigationTree::item {
    height: 30px;
    padding-left: 6px;
}

QTreeWidget#navigationTree::item:selected {
    background: #dceafe;
    color: #153c7a;
}

QFrame.pageFrame {
    background: #f5f7fb;
}

QLabel.pageTitle {
    font-size: 20px;
    font-weight: 600;
    color: #263445;
    padding: 0 0 8px 0;
}

QFrame.card {
    background: #ffffff;
    border: 1px solid #dfe3ea;
    border-radius: 6px;
}

QFrame.expanderCard {
    background: #ffffff;
    border: 1px solid #dfe3ea;
    border-radius: 6px;
}

QToolButton.expanderHeader {
    border: none;
    background: #ffffff;
    color: #263445;
    font-size: 14px;
    font-weight: 600;
    padding: 8px 10px;
}

QToolButton.expanderHeader:hover {
    background: #f4f7fc;
}

QFrame.expanderContent {
    border-top: 1px solid #edf0f5;
    background: #ffffff;
}

QLabel.cardTitle {
    font-size: 14px;
    font-weight: 600;
    color: #263445;
}

QLabel.fieldLabel {
    color: #59697d;
}

QLabel.valueLabel {
    color: #1d2b3a;
    font-family: Consolas, "Cascadia Mono", monospace;
}

QFrame.warningBanner {
    background: #fff8e5;
    border: 1px solid #f3d28a;
    border-radius: 6px;
}

QLabel.warningText {
    color: #7a5600;
    font-weight: 500;
}

QTableWidget {
    background: #ffffff;
    border: 1px solid #dfe3ea;
    gridline-color: #edf0f5;
    font-family: Consolas, "Cascadia Mono", monospace;
}

QHeaderView::section {
    background: #f0f3f8;
    border: none;
    border-right: 1px solid #dfe3ea;
    padding: 4px;
    font-weight: 600;
}

QFrame#bottomDock {
    background: #ffffff;
    border-top: 1px solid #d5d9e2;
}

QFrame#bottomDockHeader {
    background: #f7f9fc;
    border-bottom: 1px solid #dfe3ea;
}

QFrame#bottomConsoleBody {
    background: #ffffff;
    border: 1px solid #dfe3ea;
    border-radius: 6px;
}

QTextEdit#consoleOutput {
    background: #fcfdff;
    color: #263445;
    border: none;
    font-family: Consolas, "Cascadia Mono", monospace;
    font-size: 12px;
}
"""
