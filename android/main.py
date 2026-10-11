import os
from datetime import datetime
from pathlib import Path

from kivy.app import App
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput


APP_TITLE = "Evolution System v7.7.7 Absoluta"
CREATOR = "Juan Camilo Mazo González (jcmgru)"
ORGANIZATION = "Proyectos Geniales"
CONTACT = "jcmgru7@gmail.com"


class EvolutionAndroidApp(App):
    def build(self):
        self.title = APP_TITLE
        self.log_path = Path(self.user_data_dir) / "node_activity.txt"
        self.username_input = TextInput(
            hint_text="Nombre de usuario para este dispositivo",
            multiline=False,
            size_hint_y=None,
            height=dp(48),
        )

        page = BoxLayout(
            orientation="vertical",
            padding=dp(16),
            spacing=dp(10),
            size_hint_y=None,
        )
        page.bind(minimum_height=page.setter("height"))
        page.add_widget(
            Label(
                text=APP_TITLE,
                font_size="22sp",
                bold=True,
                size_hint_y=None,
                height=dp(64),
            )
        )
        page.add_widget(
            Label(
                text="Creador: {} | {} | {}".format(CREATOR, ORGANIZATION, CONTACT),
                size_hint_y=None,
                height=dp(48),
            )
        )
        page.add_widget(
            Label(
                text=(
                    "Port móvil complementario. No se conecta a la colmena ni recibe "
                    "trabajos remotos. El procesamiento compartido no está configurado."
                ),
                size_hint_y=None,
                height=dp(88),
            )
        )
        page.add_widget(self.username_input)
        page.add_widget(
            self._button("Activar registro local", self.register_node)
        )
        page.add_widget(
            self._button("[A] Revisar información local", self.audit_device)
        )
        page.add_widget(
            self._button("[S] Mantenimiento", self.show_mobile_limits)
        )
        page.add_widget(
            self._button("[C] Panel local", self.audit_device)
        )
        page.add_widget(
            self._button("[M] Estado de la malla", self.show_mesh_status)
        )
        page.add_widget(
            self._button("[V] Ver registro local", self.show_local_log)
        )
        page.add_widget(
            self._button("[E] Salir", self.stop)
        )
        self.output = Label(
            text="Registra este dispositivo voluntariamente para continuar.",
            size_hint_y=None,
            halign="left",
            valign="top",
        )
        self.output.bind(
            texture_size=lambda widget, size: setattr(widget, "height", size[1] + dp(24))
        )
        self.output.bind(width=lambda widget, width: setattr(widget, "text_size", (width, None)))
        page.add_widget(self.output)

        scroll = ScrollView()
        scroll.add_widget(page)
        Window.clearcolor = (0.96, 0.97, 0.99, 1)
        return scroll

    @staticmethod
    def _button(text, callback):
        button = Button(
            text=text,
            size_hint_y=None,
            height=dp(48),
            background_normal="",
            background_color=(0.12, 0.32, 0.55, 1),
        )
        button.bind(on_release=callback)
        return button

    def register_node(self, *_args):
        username = self.username_input.text.strip().replace("|", "_")
        if not username:
            self.output.text = "Escribe un nombre antes de activar el registro."
            return
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as log_file:
                log_file.write(
                    "{}|nodo_secundario_voluntario|{}\n".format(username, timestamp)
                )
        except OSError as error:
            self.output.text = "No se pudo guardar el registro local:\n{}".format(error)
            return
        self.output.text = (
            "Registro local activado para {}.\n"
            "El archivo se conserva en el almacenamiento privado de esta app."
        ).format(username)

    def audit_device(self, *_args):
        try:
            processor_count = os.cpu_count() or 1
        except OSError as error:
            self.output.text = "No se pudo consultar el hardware: {}".format(error)
            return
        self.output.text = (
            "Auditoría local\n"
            "Procesadores lógicos detectados: {}\n"
            "Registro local: {}\n"
            "Dispositivos de la red: no disponible; la malla no está conectada."
        ).format(processor_count, self.log_path)

    def show_mobile_limits(self, *_args):
        self.output.text = (
            "El mantenimiento SFC y Windows Defender es exclusivo de Windows. "
            "Android no modificará ni limpiará datos del sistema."
        )

    def show_mesh_status(self, *_args):
        self.output.text = (
            "Malla desconectada. Esta versión móvil no abre puertos, no se conecta "
            "a un servidor y no recibe código ni tareas remotas."
        )

    def show_local_log(self, *_args):
        try:
            self.output.text = (
                self.log_path.read_text(encoding="utf-8")
                if self.log_path.is_file()
                else "Todavía no hay registros locales."
            )
        except OSError as error:
            self.output.text = "No se pudo leer el registro local: {}".format(error)

    @staticmethod
    def stop(*_args):
        App.get_running_app().stop()


if __name__ == "__main__":
    EvolutionAndroidApp().run()
