
import sublime, sublime_plugin
import os
import re
import subprocess
import string
import threading
import time
import platform

plugin_directory = os.path.dirname(os.path.realpath(__file__))
toks = "toks"

type_strings = {
   "IDENTIFIER": "Identifier",
   "MACRO": "Macro",
   "MACRO_FUNCTION": "Macro function",
   "FUNCTION": "Function",
   "STRUCT": "Structure",
   "UNION": "Union",
   "ENUM": "Enum",
   "ENUM_VAL": "Enum value",
   "CLASS": "Class",
   "STRUCT_TYPE": "Structure type",
   "UNION_TYPE": "Union type",
   "ENUM_TYPE": "Enum type",
   "FUNCTION_TYPE": "function type",
   "TYPE": "Type",
   "VAR": "Variable",
   "NAMESPACE": "Namespace",
}

sub_type_strings = {
   "REF": "reference",
   "DEF": "definition",
   "DECL": "declaration",
};

def plugin_loaded():
    global toks
    creationflags = 0

    if sublime.platform() == "windows":
        toks_builtin = os.path.join(plugin_directory, "toks", sublime.platform(), "toks.exe")
        creationflags = 0x08000000
    else:
        toks_builtin = os.path.join(plugin_directory, "toks", sublime.platform() + "-" + platform.architecture()[0], "toks")

    if os.path.isfile(toks_builtin):
        try:
            if subprocess.call([toks_builtin, '--version'], creationflags=creationflags) == 0:
                toks = toks_builtin
        except:
            pass

def get_settings():
    return sublime.load_settings("SublimeToks.sublime-settings")

def get_setting(key, default=None, view=None):
    try:
        if view == None:
            view = sublime.active_window().active_view()
        s = view.settings()
        if s.has("SublimeToks_%s" % key):
            return s.get("SublimeToks_%s" % key)
    except:
        pass
    return get_settings().get(key, default)

class SublimeToksIndexer(threading.Thread):
    def __init__(self, index, filenames=None):
        super(SublimeToksIndexer, self).__init__()
        self.index = index
        self.filenames = filenames

    def index_files(self, files, cpp=False):
        if len(files) > 0:
            cmd = [toks, '-i', self.index, '-F', '-']
            if (cpp):
                cmd.extend(["-l", "CPP"])
            popen_arg_list = {
                "stdin": subprocess.PIPE,
                "stderr": subprocess.PIPE
            }
            if (sublime.platform() == "windows"):
                popen_arg_list["creationflags"] = 0x08000000

            try:
                proc = subprocess.Popen(cmd, **popen_arg_list)
                output = proc.communicate(bytes('\n'.join(files), 'UTF-8'))[1].decode("utf-8").splitlines()
            except FileNotFoundError:
                if self.filenames == None: # only error when doing an explicit full indexing
                    sublime.error_message("SublimeToks: Failed to invoke the toks indexer, please make sure you have it installed and added to the search path")
            else:
                if proc.returncode != 0:
                    if "Wrong index format version, delete it to continue" in output:
                        os.unlink(self.index)
                        self.filenames = None; # Upconvert to full indexing
                        self.run()

    def run(self):
        sources = []
        headers = []
        cpp = 0
        c = 0
        m = re.compile("\\.(" + re.escape(get_setting("filename_extensions")).replace("\\|", "|") + ")$")
        mcpp = re.compile("\\.(cpp|cxx|cc|cp|C|CPP|c\\+\\+)$")
        for pdir in sublime.active_window().folders():
            for root, dirs, files in os.walk(pdir):
                for file in files:
                    extension = os.path.normcase(os.path.splitext(file)[1])
                    if m.match(extension):
                        filename = os.path.join(root, file)
                        if self.filenames == None or filename in self.filenames:
                            if extension == ".h":
                                headers.append(filename)
                            else:
                                sources.append(filename)
                        if extension == ".c":
                            c += 1
                        elif mcpp.match(extension):
                            cpp += 1
        self.index_files(headers, cpp > c)
        self.index_files(sources)


class SublimeToksSearcher(threading.Thread):
    def __init__(self, index, symbol, mode, commonprefix):
        super(SublimeToksSearcher, self).__init__()
        self.index = index
        self.symbol = symbol
        self.mode = mode
        self.commonprefix = commonprefix

    def match_output_line(self, line):
        match = None
        output = None

        match = re.match(re.escape(self.commonprefix) + '(.+:\d+:\d+) (\S+) (\S+) (\S+) \S+', line)
        if match:
            try:
                type_string = type_strings[match.group(3)] + " " + sub_type_strings[match.group(4)]
            except KeyError:
                type_string = match.group(3) + " " + match.group(4)
            output = [match.group(1), match.group(2), type_string]
        return output

    def run(self):
        cmd = [toks, '-i', self.index, '--id', self.symbol]
        if self.mode != "any":
            cmd.append('--' + str(self.mode))
        popen_arg_list = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE
        }
        if (sublime.platform() == "windows"):
            popen_arg_list["creationflags"] = 0x08000000

        self.matches = []
        try:
            proc = subprocess.Popen(cmd, **popen_arg_list)
            output = proc.communicate()[0].decode("utf-8").splitlines()
        except FileNotFoundError:
            sublime.error_message("SublimeToks: Failed to invoke the toks indexer, please make sure you have it installed and added to the search path")
        else:
            if proc.returncode == 0:
                for line in output:
                    match = self.match_output_line(line)
                    if match != None:
                        self.matches.append(match)

class ToksEventListener(sublime_plugin.EventListener):
    def on_post_save(self, view):
        view.window().run_command("toks", {"mode": "index_one", "filename": view.file_name()})

class ToksCommand(sublime_plugin.WindowCommand):
    def __init__(self, window):
        super(ToksCommand, self).__init__(window)
        self.worker = None
        self.back_lines = []
        self.forward_lines = []
        self.index_one_files = []

    def find_commonprefix(self):
        folders = sublime.active_window().folders()
        commonprefix = os.path.commonprefix(folders)
        if commonprefix == "":
            return commonprefix # Avoid normpath converting "" to "."
        commonprefix = os.path.normpath(commonprefix) # strip trailing sep
        if not os.path.isdir(commonprefix):
            commonprefix = os.path.dirname(commonprefix) # strip incomplete dir
        if commonprefix == "/": # do not treat root dir as a common prefix
            return ""
        if os.path.splitdrive(commonprefix)[1] != os.path.sep:
            commonprefix = commonprefix + os.path.sep
        return commonprefix

    def active_view_position(self):
        row, col = self.view.rowcol(self.view.sel()[0].a)
        return self.view.file_name() + ":" + str(row + 1) + ":" + str(col + 1)

    def is_same_location(self, pos1, pos2):
        match1 = re.match("([^:]+):(\d+):(\d+)", pos1)
        match2 = re.match("([^:]+):(\d+):(\d+)", pos2)
        if match1.group(1) == match2.group(1) and \
           match1.group(2) == match2.group(2) and \
           match1.group(3) == match2.group(3):
            return True
        return False

    def is_history_empty(self):
        return len(self.back_lines) == 0

    def is_future_empty(self):
        return len(self.forward_lines) == 0

    def navigate_back(self):
        if not self.is_history_empty():
            current_position = self.active_view_position()
            if self.is_future_empty() or not self.is_same_location(self.forward_lines[0], current_position):
                self.forward_lines.insert(0, current_position)
            while len(self.back_lines) > 1 and self.is_same_location(self.back_lines[0], current_position):
                self.back_lines = self.back_lines[1:]
            if not self.is_history_empty():
                encoded_position = self.back_lines[0]
                sublime.active_window().open_file(encoded_position, sublime.ENCODED_POSITION)
                while len(self.forward_lines) > 1 and self.is_same_location(self.forward_lines[0], encoded_position):
                    self.forward_lines = self.forward_lines[1:]

    def navigate_forward(self):
        if not self.is_future_empty():
            encoded_position = self.forward_lines[0]
            self.forward_lines = self.forward_lines[1:]
            current_position = self.active_view_position()
            if self.is_history_empty() or not self.is_same_location(self.back_lines[0], current_position):
                self.back_lines.insert(0, current_position)
            if self.is_history_empty() or not self.is_same_location(self.back_lines[0], encoded_position):
                self.back_lines.insert(0, encoded_position)
            sublime.active_window().open_file(encoded_position, sublime.ENCODED_POSITION)

    def navigate_jump(self, source, destination):
        if self.is_history_empty() or not self.is_same_location(self.back_lines[0], source):
            self.back_lines.insert(0, source)
        if self.is_history_empty() or not self.is_same_location(self.back_lines[0], destination):
            self.back_lines.insert(0, destination)
        self.forward_lines = []
        sublime.active_window().open_file(destination, sublime.ENCODED_POSITION)

    def on_select(self, index):
        if index != -1:
            location = os.path.join(self.commonprefix, self.worker.matches[index][0])
            self.navigate_jump(self.pre_lookup_position, location)
        else:
            sublime.active_window().open_file(self.pre_lookup_position, sublime.ENCODED_POSITION)

    def on_highlighted(self, index):
        location = os.path.join(self.commonprefix, self.worker.matches[index][0])
        sublime.active_window().open_file(location, sublime.ENCODED_POSITION | sublime.TRANSIENT)

    def update_status(self, message, complete, count=0, dir=1):
        if self.worker.is_alive():
            count = count + dir
            if count == 7:
                dir = -1
            elif count == 0:
                dir = 1
            self.view.set_status("SublimeToks", message + " [%s=%s]" % (' ' * count, ' ' * (7 - count)))
            sublime.set_timeout(lambda: self.update_status(message, complete, count, dir), 100)
        else:
            self.view.erase_status("SublimeToks")
            if complete:
                complete()

    def deferred_index_one(self):
        if self.worker and self.worker.is_alive():
            sublime.set_timeout(lambda: self.deferred_index_one(), 500)
        else:
            self.worker = SublimeToksIndexer(self.index, self.index_one_files)
            self.index_one_files = []
            self.worker.start()

    def run(self, mode, filename=None):
        project_file_name = self.window.project_file_name()
        if not project_file_name and mode != "index_one":
            sublime.error_message("SublimeToks: Please create a project to enable indexing")
            return

        self.index = project_file_name.replace(".sublime-project", ".sublime-toks")
        if self.index == project_file_name:
            self.index = project_file_name + ".sublime-toks"
        self.view = self.window.active_view()

        if mode == "back":
            self.navigate_back()
            return

        if mode == "forward":
            self.navigate_forward()
            return

        if mode == "index_one":
            self.index_one_files.append(filename)
            if len(self.index_one_files) == 1:
                sublime.set_timeout(lambda: self.deferred_index_one(), 500)
            return

        if self.worker and self.worker.is_alive():
            return

        self.mode = mode

        # Check if index exists
        if mode == "index" or not os.path.isfile(self.index):
            self.worker = SublimeToksIndexer(self.index)
            self.worker.start()
            self.update_status("Indexing", self.on_indexing_complete)
            return

        self.on_indexing_complete()

    def on_indexing_complete(self):

        if self.mode == "index":
            return

        # Save the pre lookup position
        self.pre_lookup_position = self.active_view_position()

        # Search for the first word that is selected.
        first_selection = self.view.word(self.view.sel()[0])
        symbol = self.view.substr(first_selection)

        # Show only the one selection picked for search
        self.view.sel().clear()
        self.view.sel().add(first_selection)

        if get_setting("prompt_before_searching") == True:
            sublime.active_window().show_input_panel('Toks Symbol To Search:',
                                                     symbol,
                                                     self.on_search_confirmed,
                                                     None,
                                                     None)
        else:
            self.on_search_confirmed(symbol)

    def on_search_confirmed(self, symbol):
        self.commonprefix = self.find_commonprefix()
        self.worker = SublimeToksSearcher(
                index = self.index,
                symbol = symbol,
                mode = self.mode,
                commonprefix = self.commonprefix)
        self.worker.start()
        self.update_status("Searching", self.on_lookup_complete)

    def on_lookup_complete(self):
        sublime.active_window().show_quick_panel(self.worker.matches, self.on_select, 0, 0, self.on_highlighted)
