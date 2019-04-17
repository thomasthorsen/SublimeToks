
import sublime, sublime_plugin
import os
import stat
import re
import subprocess
import string
import threading
import time
import platform
import html

from operator import itemgetter

plugin_directory = os.path.dirname(os.path.realpath(__file__))
toks = "toks"
rg = "rg"

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
    global rg
    creationflags = 0

    if sublime.platform() == "windows":
        toks_builtin = os.path.join(plugin_directory, "toks", sublime.platform(), "toks.exe")
        rg_builtin = os.path.join(plugin_directory, "ripgrep", sublime.platform(), "rg.exe")
        creationflags = 0x08000000
    elif sublime.platform() == "linux":
        toks_builtin = os.path.join(plugin_directory, "toks", sublime.platform() + "-" + platform.architecture()[0], "toks")
        rg_builtin = os.path.join(plugin_directory, "ripgrep", sublime.platform() + "-" + platform.architecture()[0], "toks")
        if os.path.isfile(toks_builtin):
            os.chmod(toks_builtin, (os.stat(toks_builtin).st_mode | stat.S_IXUSR))
        if os.path.isfile(rg_builtin):
            os.chmod(rg_builtin, (os.stat(rg_builtin).st_mode | stat.S_IXUSR))

    if os.path.isfile(toks_builtin):
        try:
            if subprocess.call([toks_builtin, '--version'], creationflags=creationflags) == 0:
                toks = toks_builtin
        except:
            pass

    if os.path.isfile(rg_builtin):
        try:
            if subprocess.call([rg_builtin, '--version'], creationflags=creationflags) == 0:
                rg = rg_builtin
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

class SublimeToksSearcher(threading.Thread):
    def __init__(self, index, symbol, mode, commonprefix, view):
        super(SublimeToksSearcher, self).__init__()
        self.index = index
        self.symbol = symbol
        self.mode = mode
        self.commonprefix = commonprefix
        self.view = view
        self.matches = []
        self.total_file_count = 0
        self.total_file_processed = 0

    def index_files(self, files, cpp=False):
        count = 0
        while len(files) > 0:
            progress = round(100 * self.total_file_processed / self.total_file_count)
            self.view.set_status("SublimeToks", "Searching [%d%%]" % progress)
            slice_of_files = files[:8]
            del files[:len(slice_of_files)]
            self.total_file_processed += len(slice_of_files)
            cmd = [toks, '-i', self.index, '-F', '-']
            if (cpp):
                cmd.extend(["-l", "CPP"])
            popen_arg_list = {"stdin": subprocess.PIPE, "stderr": subprocess.PIPE}
            if (sublime.platform() == "windows"):
                popen_arg_list["creationflags"] = 0x08000000

            try:
                proc = subprocess.Popen(cmd, **popen_arg_list)
                output = proc.communicate(bytes('\n'.join(slice_of_files), 'UTF-8'))[1].decode("utf-8").splitlines()
            except FileNotFoundError:
                sublime.error_message("SublimeToks: Failed to invoke the toks indexer, please make sure you have it installed and added to the search path")
            else:
                if proc.returncode != 0:
                    if "Wrong index format version, delete it to continue" in output:
                        os.unlink(self.index)
                        self.run()

    def match_output_line(self, line):
        match = re.match(re.escape(self.commonprefix) + '(.+):(\d+):(\d+) (\S+) (\S+) (\S+) \S+', line)
        if match:
            try:
                type_string = type_strings[match.group(5)] + " " + sub_type_strings[match.group(6)]
            except KeyError:
                type_string = match.group(5) + " " + match.group(6)
            self.matches.append([match.group(1), int(match.group(2)), int(match.group(3)), match.group(4), type_string])

    def to_globs(self, iterable):
        for item in iterable:
            yield "-g"
            yield "*." + item

    def run(self):
        # Find files
        self.view.set_status("SublimeToks", "Searching...")
        extensions = get_setting("filename_extensions", "c|h|cpp|hpp|cxx|hxx|cc|cp|C|CPP|c++")
        globs = list(self.to_globs(extensions.split("|")))
        symbol = self.symbol.replace("*", ".*").replace("?", ".")
        cmd = [rg, "--files-with-matches"] + globs + [symbol] + sublime.active_window().folders()
        popen_arg_list = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
        if (sublime.platform() == "windows"):
            popen_arg_list["creationflags"] = 0x08000000

        try:
            proc = subprocess.Popen(cmd, **popen_arg_list)
            files = proc.communicate()[0].decode("utf-8").splitlines()
        except FileNotFoundError:
            sublime.error_message("SublimeToks: Failed to invoke ripgrep, please make sure you have it installed and added to the search path")
        else:
            if proc.returncode != 0:
                # No results or possibly other error
                self.view.erase_status("SublimeToks")
                return

        # Index found files
        sources = []
        headers = []
        cpp = 0
        c = 0
        m = re.compile("\\.(" + re.escape(get_setting("filename_extensions",
                                                      "c|h|cpp|hpp|cxx|hxx|cc|cp|C|CPP|c++")).replace("\\|", "|") + ")$")
        mcpp = re.compile("\\.(cpp|cxx|cc|cp|C|CPP|c\\+\\+)$")
        for file in files:
            extension = os.path.normcase(os.path.splitext(file)[1])
            if m.match(extension):
                if extension == ".h":
                    headers.append(file)
                else:
                    sources.append(file)
                if extension == ".c":
                    c += 1
                elif mcpp.match(extension):
                    cpp += 1
        self.total_file_count = len(headers) + len(sources)
        self.index_files(headers, cpp > c)
        self.index_files(sources)
        self.view.set_status("SublimeToks", "Searching...")

        # Lookup in index
        cmd = [toks, '-i', self.index, '--id', self.symbol]
        if self.mode != "any":
            cmd.append('--' + str(self.mode))
        popen_arg_list = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE
        }
        if (sublime.platform() == "windows"):
            popen_arg_list["creationflags"] = 0x08000000

        try:
            proc = subprocess.Popen(cmd, **popen_arg_list)
            output = proc.communicate()[0].decode("utf-8").splitlines()
        except FileNotFoundError:
            sublime.error_message("SublimeToks: Failed to invoke the toks indexer, please make sure you have it installed and added to the search path")
        else:
            if proc.returncode == 0:
                for line in output:
                    self.match_output_line(line)
                self.matches.sort(key=itemgetter(0, 1, 2))
                for match in self.matches:
                    match[0] += ":" + str(match[1])
                    del match[1]
                    match[0] += ":" + str(match[1])
                    del match[1]
        self.view.erase_status("SublimeToks")

class ToksOutputPanel():
    def __init__(self, symbol, current_position, matches, commonprefix):
        self.name = "Toks: " + symbol
        sublime.active_window().destroy_output_panel(self.name)
        self.op = sublime.active_window().create_output_panel(self.name)
        sublime.active_window().run_command("show_panel", {"panel": "output." + self.name})

        contents = "<b><a href=$hide style=\"text-decoration: none\">" + chr(0x00D7) + "</a> " + symbol + "</b>"
        if isinstance(current_position, str):
            contents += " (<a href=" + os.path.join(commonprefix, current_position) + ">" + current_position + "</a>)"
        else:
            contents += " (<a href=$back>" + "unsaved view" + "</a>)"
            self.pre_lookup_view = current_position
        contents += "<ul>"

        for match in matches:
            contents += "<li><a href=" + os.path.join(commonprefix, match[0]) + ">" + match[0] + "</a> " + html.escape(match[1], quote=False) + " " + match[2] + "</li>"

        contents += "</ul>"

        self.phantom = sublime.Phantom(self.op.sel()[0], '<body>' + contents + '</body>', sublime.LAYOUT_INLINE, on_navigate=self.on_phantom_navigate)
        self.phantomset = sublime.PhantomSet(self.op, "toks")
        self.phantomset.update([self.phantom])

    def on_phantom_navigate(self, url):
        if url == "$hide":
            sublime.active_window().destroy_output_panel(self.name)
        elif url == "$back":
            sublime.active_window().focus_view(self.pre_lookup_view)
        else:
            sublime.active_window().open_file(url, sublime.ENCODED_POSITION)
        return

class ToksCommand(sublime_plugin.WindowCommand):
    def __init__(self, window):
        super(ToksCommand, self).__init__(window)
        self.worker = None
        self.back_lines = []
        self.forward_lines = []
        self.quick_panel_index = 0
        self.quick_panel_ignore_cancel = False

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
        file_name = self.view.file_name()
        if file_name:
            return file_name + ":" + str(row + 1) + ":" + str(col + 1)

    def is_same_location(self, pos1, pos2):
        match1 = re.match("(.+):(\d+):(\d+)", pos1)
        match2 = re.match("(.+):(\d+):(\d+)", pos2)
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
            if current_position:
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
            if current_position:
                if self.is_history_empty() or not self.is_same_location(self.back_lines[0], current_position):
                    self.back_lines.insert(0, current_position)
                if self.is_history_empty() or not self.is_same_location(self.back_lines[0], encoded_position):
                    self.back_lines.insert(0, encoded_position)
            sublime.active_window().open_file(encoded_position, sublime.ENCODED_POSITION)

    def navigate_jump(self, source, destination):
        if source:
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
            if self.quick_panel_ignore_cancel:
                self.quick_panel_ignore_cancel = False
            elif self.pre_lookup_position:
                sublime.active_window().open_file(self.pre_lookup_position, sublime.ENCODED_POSITION)
            elif self.pre_lookup_view:
                sublime.active_window().focus_view(self.pre_lookup_view)

    def on_highlighted(self, index):
        location = os.path.join(self.commonprefix, self.worker.matches[index][0])
        match = re.match("(.+):\d+:\d+", location)
        view = sublime.active_window().find_open_file(match.group(1))
        if view:
            active_group = sublime.active_window().active_group()
            group = sublime.active_window().get_view_index(view)[0]
            if active_group != group:
                self.quick_panel_ignore_cancel = True
                sublime.active_window().run_command("hide_overlay")
        sublime.active_window().open_file(location, sublime.ENCODED_POSITION | sublime.TRANSIENT)
        if view and active_group != group:
            self.quick_panel_index = index
            self.on_lookup_complete()

    def check_status(self, complete):
        if self.worker.is_alive():
            sublime.set_timeout(lambda: self.check_status(complete), 100)
        else:
            if complete:
                complete()

    def run(self, mode, filename=None, prompt=False, report=False):
        project_file_name = self.window.project_file_name()
        if not project_file_name:
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

        if self.worker and self.worker.is_alive():
            return

        self.mode = mode
        self.prompt = prompt
        self.report = report

        # Save the pre lookup position
        self.pre_lookup_position = self.active_view_position()
        self.pre_lookup_view = self.view

        # Search for the first word that is selected.
        first_selection = self.view.word(self.view.sel()[0])
        symbol = self.view.substr(first_selection).strip()

        # Show only the one selection picked for search
        self.view.sel().clear()
        self.view.sel().add(first_selection)

        if self.prompt:
            sublime.active_window().show_input_panel('Search:',
                                                     symbol,
                                                     self.on_search_confirmed,
                                                     None,
                                                     None)
        else:
            self.on_search_confirmed(symbol)

    def on_search_confirmed(self, symbol):
        self.symbol = symbol
        self.commonprefix = self.find_commonprefix()
        self.worker = SublimeToksSearcher(
                index = self.index,
                symbol = symbol,
                mode = self.mode,
                commonprefix = self.commonprefix,
                view = self.view
                )
        self.worker.start()
        self.quick_panel_index = 0
        self.check_status(self.on_lookup_complete)

    def on_lookup_complete(self):
        if self.report:
            ToksOutputPanel(self.symbol, self.pre_lookup_position or self.pre_lookup_view, self.worker.matches, self.commonprefix)
        else:
            sublime.active_window().show_quick_panel(self.worker.matches, self.on_select, sublime.KEEP_OPEN_ON_FOCUS_LOST, self.quick_panel_index, self.on_highlighted)


