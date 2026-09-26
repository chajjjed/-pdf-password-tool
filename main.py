"""
PDF Password Tool - Android App (built with Buildozer)
---------------------------------------------------------
- Pick one or more password-protected PDFs.
- The app tries all passwords in your saved "password pool" automatically.
- If one matches, it unlocks the file automatically.
- If none match, it asks you for the password, checks it, saves it to the
  pool for next time, and unlocks the file.

Unlocked files are saved in the SAME folder as the original,
named "<filename>_unlocked.pdf".
"""

import os
import json

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.popup import Popup
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.scrollview import ScrollView
from kivy.uix.checkbox import CheckBox
from kivy.core.window import Window

from pypdf import PdfReader, PdfWriter
from pypdf.errors import FileNotDecryptedError, PdfReadError

Window.clearcolor = (0.06, 0.09, 0.16, 1)  # dark navy background

try:
    from android.permissions import request_permissions, Permission
    request_permissions([
        Permission.READ_EXTERNAL_STORAGE,
        Permission.WRITE_EXTERNAL_STORAGE,
    ])
except ImportError:
    pass  # not running on Android (e.g. testing on desktop)


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

class PasswordPopup(Popup):
    def __init__(self, filename, on_submit, on_skip, **kwargs):
        super().__init__(**kwargs)
        self.title = f"Password needed: {filename}"
        self.size_hint = (0.9, 0.4)

        layout = BoxLayout(orientation="vertical", spacing=10, padding=15)
        layout.add_widget(Label(text="No saved password matched.\nEnter the correct password:"))

        self.input = TextInput(password=True, multiline=False, size_hint_y=None, height=45)
        layout.add_widget(self.input)

        btn_row = BoxLayout(size_hint_y=None, height=45, spacing=10)
        submit_btn = Button(text="Unlock", background_color=(0.22, 0.74, 0.98, 1))
        skip_btn = Button(text="Skip File", background_color=(0.4, 0.4, 0.4, 1))
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


class MainLayout(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=15, spacing=10, **kwargs)

        self.overwrite = False
        self.queue = []
        self.queue_index = 0

        title = Label(
            text="[b]PDF Password Tool[/b]",
            markup=True,
            font_size=24,
            size_hint_y=None,
            height=45,
            color=(0.22, 0.74, 0.98, 1),
        )
        self.add_widget(title)

        subtitle = Label(
            text="Unlocks PDFs using your saved password pool.",
            font_size=13,
            size_hint_y=None,
            height=25,
            color=(0.6, 0.65, 0.72, 1),
        )
        self.add_widget(subtitle)

        select_btn = Button(
            text="Select PDF File(s)",
            size_hint_y=None,
            height=55,
            background_color=(0.22, 0.74, 0.98, 1),
            bold=True,
        )
        select_btn.bind(on_release=self.open_file_chooser)
        self.add_widget(select_btn)

        checkbox_row = BoxLayout(size_hint_y=None, height=35, spacing=8)
        self.checkbox = CheckBox(size_hint_x=None, width=35)
        self.checkbox.bind(active=self.on_checkbox)
        checkbox_row.add_widget(self.checkbox)
        checkbox_row.add_widget(Label(text="Overwrite original file instead of saving a copy",
                                       font_size=12, color=(0.85, 0.87, 0.9, 1)))
        self.add_widget(checkbox_row)

        view_btn = Button(
            text="View Saved Passwords",
            size_hint_y=None,
            height=40,
            background_color=(0.15, 0.19, 0.27, 1),
        )
        view_btn.bind(on_release=self.view_pool)
        self.add_widget(view_btn)

        self.add_widget(Label(text="Activity Log:", size_hint_y=None, height=25,
                               halign="left", color=(0.85, 0.87, 0.9, 1)))

        self.log_label = Label(
            text="", font_size=12, size_hint_y=None, halign="left", valign="top",
            color=(0.85, 0.87, 0.9, 1),
        )
        self.log_label.bind(width=lambda *x: self.log_label.setter("text_size")(
            self.log_label, (self.log_label.width, None)))
        self.log_label.bind(texture_size=lambda *x: setattr(
            self.log_label, "height", self.log_label.texture_size[1]))

        scroll = ScrollView()
        scroll.add_widget(self.log_label)
        self.add_widget(scroll)

        self.log(f"Password pool has {len(load_pool())} saved password(s).")
        self.log("Unlocked files save in the same folder as the original.")

    def on_checkbox(self, checkbox, value):
        self.overwrite = value

    def log(self, message):
        self.log_label.text += ("\n" if self.log_label.text else "") + message

    def view_pool(self, *args):
        passwords = load_pool()
        text = "\n".join(f"{i+1}. {pw}" for i, pw in enumerate(passwords)) or "No passwords saved yet."
        popup = Popup(title="Saved Passwords", size_hint=(0.85, 0.6),
                       content=Label(text=text))
        popup.open()

    def open_file_chooser(self, *args):
        start_path = "/storage/emulated/0/"
        if not os.path.exists(start_path):
            start_path = os.path.expanduser("~")

        chooser = FileChooserListView(
            path=start_path,
            filters=["*.pdf"],
            multiselect=True,
        )
        layout = BoxLayout(orientation="vertical")
        layout.add_widget(chooser)

        btn_row = BoxLayout(size_hint_y=None, height=50, spacing=10)
        select_btn = Button(text="Select", background_color=(0.22, 0.74, 0.98, 1))
        cancel_btn = Button(text="Cancel", background_color=(0.4, 0.4, 0.4, 1))
        btn_row.add_widget(select_btn)
        btn_row.add_widget(cancel_btn)
        layout.add_widget(btn_row)

        popup = Popup(title="Select PDF file(s)", content=layout, size_hint=(0.95, 0.95))

        def confirm(*a):
            files = list(chooser.selection)
            popup.dismiss()
            if files:
                self.start_batch(files)

        select_btn.bind(on_release=confirm)
        cancel_btn.bind(on_release=popup.dismiss)
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
