"""
PDF Password Tool - Android Version (runs inside Pydroid 3)
-------------------------------------------------------------
Same idea as the Windows version:
- Pick one or more password-protected PDFs.
- The app tries all passwords in your saved "password pool" automatically.
- If one matches, it unlocks the file automatically.
- If none match, it asks you for the password, checks it, saves it to the
  pool for next time, and unlocks the file.

Unlocked files are saved in the SAME folder as the original,
named "<filename>_unlocked.pdf".

Requirements (install once inside Pydroid 3's Pip screen):
    kivy
    pypdf
"""

import os
import json

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.checkbox import CheckBox
from kivy.core.window import Window

from pypdf import PdfReader, PdfWriter
from pypdf.errors import FileNotDecryptedError, PdfReadError

Window.clearcolor = (0.06, 0.09, 0.16, 1)  # dark navy background
try:
    Window.softinput_mode = "below_target"  # shift screen up so keyboard never covers the focused input
except Exception:
    pass


# ---------- Password pool helpers ----------

def get_pool_path():
    app = App.get_running_app()
    folder = app.user_data_dir  # private, persistent app storage on the phone
    return os.path.join(folder, "password_pool.json")


def load_pool():
    path = get_pool_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def save_pool(passwords):
    with open(get_pool_path(), "w", encoding="utf-8") as f:
        json.dump(passwords, f, indent=2, ensure_ascii=False)


def add_password_to_pool(password):
    passwords = load_pool()
    if password not in passwords:
        passwords.append(password)
        save_pool(passwords)


# ---------- Core PDF logic (pypdf) ----------

def is_encrypted(pdf_path):
    reader = PdfReader(pdf_path)
    return reader.is_encrypted


def try_password(pdf_path, password):
    """Return True if this password successfully decrypts the PDF."""
    try:
        reader = PdfReader(pdf_path)
        if not reader.is_encrypted:
            return True
        result = reader.decrypt(password)
        return result != 0  # pypdf returns 0 on failure
    except (FileNotDecryptedError, PdfReadError, Exception):
        return False


def try_known_passwords(pdf_path, passwords):
    for pw in passwords:
        if try_password(pdf_path, pw):
            return pw
    return None


def save_unlocked_copy(pdf_path, password, overwrite=False):
    reader = PdfReader(pdf_path)
    if reader.is_encrypted:
        reader.decrypt(password)

    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)

    folder = os.path.dirname(os.path.abspath(pdf_path))
    base_name = os.path.splitext(os.path.basename(pdf_path))[0]

    if overwrite:
        out_path = pdf_path
    else:
        out_path = os.path.join(folder, f"{base_name}_unlocked.pdf")
        counter = 1
        while os.path.exists(out_path):
            out_path = os.path.join(folder, f"{base_name}_unlocked_{counter}.pdf")
            counter += 1

    with open(out_path, "wb") as f:
        writer.write(f)

    return out_path


# ---------- UI ----------

class HelpPopup(Popup):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.title = "How it Works"
        self.title_size = 40
        self.size_hint = (0.9, 0.7)
        self.pos_hint = {"top": 0.95}

        layout = BoxLayout(orientation="vertical", spacing=15, padding=20)
        
        help_text = (
            "Welcome to the PDF Password Tool!\n\n"
            "This app unlocks password-protected PDFs and remembers the passwords so you don't have to type them again.\n\n"
            "1. Select your locked PDF file(s).\n"
            "2. If the app doesn't know the password yet, it will ask you for it.\n"
            "3. Once entered, the password is saved to your secure 'Password Pool'.\n"
            "4. Next time you open a PDF with that same password, it unlocks instantly and automatically!\n\n"
            "Unlocked files are safely saved in the same folder as the original."
        )

        lbl = Label(text=help_text, font_size=34, halign="left", valign="top", color=(0.9, 0.95, 0.95, 1))
        lbl.bind(width=lambda *x: lbl.setter("text_size")(lbl, (lbl.width, None)))
        layout.add_widget(lbl)

        close_btn = Button(text="Got it!", font_size=42, size_hint_y=None, height=75, background_color=(0.22, 0.74, 0.98, 1))
        close_btn.bind(on_release=self.dismiss)
        layout.add_widget(close_btn)

        self.content = layout


class PasswordPopup(Popup):
    def __init__(self, filename, on_submit, on_skip, **kwargs):
        super().__init__(**kwargs)
        self.title = f"Password needed for: {filename}"
        self.title_size = 40
        self.size_hint = (0.9, 0.5)
        self.pos_hint = {"top": 0.98}

        layout = BoxLayout(orientation="vertical", spacing=14, padding=18)
        layout.add_widget(Label(text="No saved password matched.\nEnter the correct password:",
                                 font_size=42))

        self.input = TextInput(password=True, multiline=False, font_size=54,
                                size_hint_y=None, height=75)
        layout.add_widget(self.input)

        btn_row = BoxLayout(size_hint_y=None, height=75, spacing=10)
        submit_btn = Button(text="Unlock", font_size=42, background_color=(0.22, 0.74, 0.98, 1))
        skip_btn = Button(text="Skip File", font_size=42, background_color=(0.4, 0.4, 0.4, 1))
        btn_row.add_widget(submit_btn)
        btn_row.add_widget(skip_btn)
        layout.add_widget(btn_row)

        self.content = layout
        self._on_submit = on_submit
        self._on_skip = on_skip
        submit_btn.bind(on_release=self._submit)
        skip_btn.bind(on_release=self._skip)

    def _submit(self, *args):
        pw = self.input.text
        self.dismiss()
        self._on_submit(pw)

    def _skip(self, *args):
        self.dismiss()
        self._on_skip()


class PDFChooserPopup(Popup):
    """Custom File Chooser with Checkboxes for picking multiple PDFs easily"""
    def __init__(self, on_confirm, **kwargs):
        super().__init__(**kwargs)
        self.title = "Select PDF File(s)"
        self.title_size = 36
        self.size_hint = (0.95, 0.95)
        self.on_confirm = on_confirm
        self.selected_files = set()
        
        # Determine starting path
        base = os.path.expanduser("~/storage/shared")
        if not os.path.exists(base):
            base = "/storage/emulated/0/"
        self.current_path = base
        
        self.main_layout = BoxLayout(orientation='vertical', spacing=10, padding=10)
        
        # Top Path Label
        self.path_label = Label(text=self.current_path, font_size=24, size_hint_y=None, height=45, color=(0.7, 0.75, 0.8, 1))
        self.path_label.bind(size=lambda b, s: b.setter('text_size')(b, (s[0], s[1])))
        self.path_label.bind(valign=lambda b, v: setattr(b, 'valign', 'middle'))
        self.main_layout.add_widget(self.path_label)
        
        # Scrollable area for folders and files
        self.scroll = ScrollView()
        self.list_layout = BoxLayout(orientation='vertical', size_hint_y=None, spacing=8)
        self.list_layout.bind(minimum_height=self.list_layout.setter('height'))
        self.scroll.add_widget(self.list_layout)
        self.main_layout.add_widget(self.scroll)
        
        # Selection counter
        self.status_label = Label(
            text="0 files selected", 
            font_size=32, 
            color=(0.98, 0.82, 0.22, 1), 
            bold=True,
            size_hint_y=None, height=50
        )
        self.main_layout.add_widget(self.status_label)

        # Bottom Buttons
        bottom_btn_row = BoxLayout(size_hint_y=None, height=70, spacing=10)
        start_btn = Button(text="Unlock Batch", font_size=34, background_color=(0.22, 0.74, 0.98, 1))
        cancel_btn = Button(text="Cancel", font_size=34, background_color=(0.4, 0.4, 0.4, 1))
        bottom_btn_row.add_widget(start_btn)
        bottom_btn_row.add_widget(cancel_btn)
        self.main_layout.add_widget(bottom_btn_row)
        
        start_btn.bind(on_release=self._confirm)
        cancel_btn.bind(on_release=self.dismiss)
        
        self.content = self.main_layout
        self.populate_list(self.current_path)

    def _confirm(self, *args):
        self.dismiss()
        if self.selected_files:
            self.on_confirm(list(self.selected_files))
            
    def go_up(self):
        parent = os.path.dirname(self.current_path)
        if parent and os.path.exists(parent):
            self.current_path = parent
            self.populate_list(self.current_path)
            
    def open_dir(self, dir_name):
        new_path = os.path.join(self.current_path, dir_name)
        if os.path.exists(new_path):
            self.current_path = new_path
            self.populate_list(self.current_path)
            
    def toggle_file(self, full_path, is_active):
        if is_active:
            self.selected_files.add(full_path)
        else:
            self.selected_files.discard(full_path)
        self.status_label.text = f"{len(self.selected_files)} files selected"

    def populate_list(self, path):
        self.list_layout.clear_widgets()
        self.path_label.text = f"Folder: {path}"
        
        # Up Button
        up_btn = Button(text="[b].. Go Up a Folder[/b]", markup=True, font_size=32, size_hint_y=None, height=75, background_color=(0.3, 0.35, 0.45, 1))
        up_btn.bind(on_release=lambda x: self.go_up())
        self.list_layout.add_widget(up_btn)
        
        try:
            items = os.listdir(path)
        except Exception:
            items = []
            
        dirs = []
        files = []
        for item in items:
            if item.startswith('.'): continue
            full_item_path = os.path.join(path, item)
            if os.path.isdir(full_item_path):
                dirs.append(item)
            elif item.lower().endswith('.pdf'):
                files.append(item)
                
        dirs.sort(key=lambda s: s.lower())
        files.sort(key=lambda s: s.lower())
        
        # Add Folders
        for d in dirs:
            btn = Button(text=f"[Folder]   {d}", font_size=30, halign="left", size_hint_y=None, height=75, background_normal='', background_color=(0.15, 0.19, 0.27, 1))
            btn.bind(size=lambda b, s: b.setter('text_size')(b, (s[0]-20, s[1])))
            btn.bind(valign=lambda b, v: setattr(b, 'valign', 'middle'))
            btn.bind(on_release=lambda btn, dir_name=d: self.open_dir(dir_name))
            self.list_layout.add_widget(btn)
            
        # Add PDF Files with Checkboxes
        for f in files:
            full_path = os.path.join(path, f)
            row = BoxLayout(size_hint_y=None, height=75, spacing=15)
            
            cb = CheckBox(size_hint_x=None, width=80, color=(0.2, 1.0, 0.2, 1))
            cb.active = full_path in self.selected_files
            cb.bind(active=lambda checkbox, value, fp=full_path: self.toggle_file(fp, value))
            
            btn = Button(text=f, font_size=30, halign="left", background_normal='', background_color=(0.1, 0.13, 0.2, 1))
            btn.bind(size=lambda b, s: b.setter('text_size')(b, (s[0]-20, s[1])))
            btn.bind(valign=lambda b, v: setattr(b, 'valign', 'middle'))
            
            # Make clicking the button toggle the checkbox
            def make_toggle(checkbox):
                return lambda *args: setattr(checkbox, 'active', not checkbox.active)
                
            btn.bind(on_release=make_toggle(cb))
            
            row.add_widget(cb)
            row.add_widget(btn)
            self.list_layout.add_widget(row)


class MainLayout(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=20, spacing=24, **kwargs)

        self.overwrite = False
        self.queue = []
        self.queue_index = 0

        title = Label(
            text="[b]PDF Password Tool[/b]",
            markup=True,
            font_size=48,
            size_hint_y=None,
            height=55,
            color=(0.22, 0.74, 0.98, 1),
        )
        self.add_widget(title)

        subtitle = Label(
            text="Unlock PDFs using your saved password pool.",
            font_size=30,
            size_hint_y=None,
            height=32,
            color=(0.8, 0.85, 0.9, 1),
        )
        self.add_widget(subtitle)

        select_btn = Button(
            text="Select PDF File(s)",
            font_size=46,
            size_hint_y=None,
            height=70,
            background_color=(0.22, 0.74, 0.98, 1),
            bold=True,
        )
        select_btn.bind(on_release=self.open_file_chooser)
        self.add_widget(select_btn)

        # Centered Checkbox Row with Distinct Colors and Larger Box
        checkbox_row = BoxLayout(size_hint_y=None, height=60, spacing=15, size_hint_x=None, pos_hint={'center_x': 0.5})
        
        self.checkbox = CheckBox(size_hint=(None, None), size=(60, 60), color=(0.2, 1.0, 0.2, 1)) 
        self.checkbox.bind(active=self.on_checkbox)
        
        cb_label = Label(text="Overwrite original file instead of saving a copy",
                         font_size=38, color=(0.4, 0.9, 0.4, 1), size_hint_x=None)
        cb_label.bind(texture_size=lambda instance, size: setattr(instance, 'width', size[0]))
        
        checkbox_row.add_widget(self.checkbox)
        checkbox_row.add_widget(cb_label)
        checkbox_row.bind(minimum_width=checkbox_row.setter('width'))
        
        self.add_widget(checkbox_row)

        # Action Buttons Row (Passwords & Help side-by-side)
        action_row = BoxLayout(size_hint_y=None, height=65, spacing=15)

        view_btn = Button(
            text="View Saved Passwords",
            font_size=36,
            background_color=(0.15, 0.19, 0.27, 1),
        )
        view_btn.bind(on_release=self.view_pool)
        
        help_btn = Button(
            text="Help & Info",
            font_size=36,
            size_hint_x=0.45,
            background_color=(0.3, 0.35, 0.45, 1),
        )
        help_btn.bind(on_release=self.show_help)

        action_row.add_widget(view_btn)
        action_row.add_widget(help_btn)
        self.add_widget(action_row)

        self.add_widget(Label(text="Activity Log:", font_size=34, size_hint_y=None, height=50,
                               halign="left", color=(0.95, 0.95, 0.95, 1)))

        self.log_label = Label(
            text="", font_size=20, size_hint_y=None, halign="left", valign="top",
            color=(0.9, 0.95, 0.95, 1),
        )
        self.log_label.bind(width=lambda *x: self.log_label.setter("text_size")(
            self.log_label, (self.log_label.width, None)))
        self.log_label.bind(texture_size=lambda *x: setattr(
            self.log_label, "height", self.log_label.texture_size[1]))

        scroll = ScrollView()
        scroll.add_widget(self.log_label)
        self.add_widget(scroll)

        credit = Label(
            text="[b]By Narendra chajjed[/b]",
            markup=True,
            font_size=38,
            size_hint_y=None,
            height=35,
            halign="right",
            valign="middle",
            color=(0.98, 0.82, 0.22, 1),
        )
        credit.bind(width=lambda *x: credit.setter("text_size")(credit, (credit.width, None)))
        self.add_widget(credit)

        self.log(f"Password pool has {len(load_pool())} saved password(s).")
        self.log("Unlocked files save in the same folder as the original.")

    def show_help(self, *args):
        popup = HelpPopup()
        popup.open()

    def on_checkbox(self, checkbox, value):
        self.overwrite = value

    def log(self, message):
        self.log_label.text += ("\n" if self.log_label.text else "") + message

    def view_pool(self, *args):
        passwords = load_pool()
        text = "\n".join(f"{i+1}. {pw}" for i, pw in enumerate(passwords)) or "No passwords saved yet."
        
        content_layout = BoxLayout(orientation='vertical', size_hint_y=None, padding=15)
        
        lbl = Label(
            text=text, 
            font_size=24, 
            size_hint_y=None, 
            halign="left", 
            valign="top"
        )
        lbl.bind(width=lambda *x: lbl.setter("text_size")(lbl, (lbl.width, None)))
        lbl.bind(texture_size=lambda *x: setattr(lbl, "height", lbl.texture_size[1]))
        
        content_layout.add_widget(lbl)
        content_layout.bind(minimum_height=content_layout.setter('height'))
        
        scroll = ScrollView(size_hint=(1, 1))
        scroll.add_widget(content_layout)
        
        popup = Popup(title="Saved Passwords", title_size=30, size_hint=(0.85, 0.6), content=scroll)
        popup.open()

    def open_file_chooser(self, *args):
        popup = PDFChooserPopup(on_confirm=self.start_batch)
        popup.open()

    def start_batch(self, files):
        self.queue = files
        self.queue_index = 0
        self.log(f"\nSelected {len(files)} file(s). Starting...")
        self.process_next()

    def process_next(self):
        if self.queue_index >= len(self.queue):
            self.log("\nAll files done.")
            return

        pdf_path = self.queue[self.queue_index]
        self.queue_index += 1
        self.log(f"\n--- {os.path.basename(pdf_path)} ---")

        try:
            if not is_encrypted(pdf_path):
                self.log("Not password-protected. Skipped.")
                self.process_next()
                return
        except Exception as e:
            self.log(f"Could not read this file: {e}")
            self.process_next()
            return

        passwords = load_pool()
        found = try_known_passwords(pdf_path, passwords)

        if found is not None:
            self.log("Match found. Unlocking...")
            out_path = save_unlocked_copy(pdf_path, found, overwrite=self.overwrite)
            self.log(f"Saved: {out_path}")
            self.process_next()
            return

        self.log("No saved password matched.")
        self.ask_password(pdf_path)

    def ask_password(self, pdf_path):
        def on_submit(password):
            if not password:
                self.log("Empty password entered. Skipping file.")
                self.process_next()
                return
            if try_password(pdf_path, password):
                self.log("Password correct. Saved to pool.")
                add_password_to_pool(password)
                out_path = save_unlocked_copy(pdf_path, password, overwrite=self.overwrite)
                self.log(f"Saved: {out_path}")
                self.process_next()
            else:
                self.log("Incorrect password. Retry...")
                self.ask_password(pdf_path)

        def on_skip():
            self.log("Skipped.")
            self.process_next()

        popup = PasswordPopup(os.path.basename(pdf_path), on_submit, on_skip)
        popup.open()


class PdfPasswordApp(App):
    def build(self):
        self.title = "PDF Password Tool"
        return MainLayout()


if __name__ == "__main__":
    PdfPasswordApp().run()
