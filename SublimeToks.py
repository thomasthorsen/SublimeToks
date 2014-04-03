

import sublime, sublime_plugin
import os
import re
import subprocess
import string
import threading

import time

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

def getEncodedPosition(file_name, row, col):
    return file_name + ":" + str(row) + ":" + str(col)

def getCurrentPosition(view):
    row, col = view.rowcol(view.sel()[0].a)
    return getEncodedPosition(view.file_name(), row + 1, col + 1)

def isOnSameLine(pos1, pos2):
    match1 = re.match("([^:]+):(\d+):(\d+)", pos1)
    match2 = re.match("([^:]+):(\d+):(\d+)", pos2)
    if match1.group(1) == match2.group(1) and \
       match1.group(2) == match2.group(2) and \
       match1.group(3) == match2.group(3):
        return True
    return False

class GobackCommand(sublime_plugin.TextCommand):
    def __init__(self, view):
        self.view = view

    def run(self, edit):
        ToksCommand.navigate_back(self.view)

class ForwardCommand(sublime_plugin.TextCommand):
    def __init__(self, view):
        self.view = view

    def run(self, edit):
        ToksCommand.navigate_forward(self.view)

class SublimeToksIndexer(threading.Thread):
    def __init__(self, directory):
        super(SublimeToksIndexer, self).__init__()
        self.directory = directory
        self.matches = None

    def run(self):
        targets = []
        m = re.compile(".*\\.[ch]$")
        for pdir in sublime.active_window().folders():
            for root, dirs, files in os.walk(pdir):
                for file in files:
                    if m.match(file):
                        targets.append(os.path.join(root, file))

        cmd = ["toks -F -"]
        proc = subprocess.Popen(cmd, cwd=self.directory, shell=True,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        proc.communicate(bytes('\n'.join(targets), 'UTF-8'))
        if proc.returncode != 0:
            sublime.error_message("SublimeToks: Failed to invoke the toks indexer, please make sure you have it installed and added to the search path")

class SublimeToksSearcher(threading.Thread):

    def __init__(self, view, platform, root, database, symbol, mode):
        super(SublimeToksSearcher, self).__init__()
        self.view = view
        self.platform = platform
        self.root = root
        self.database = database
        self.symbol = symbol
        self.mode = mode

    def match_output_line(self, line):
        match = None
        output = None

        match = re.match('(.+:\d+:\d+) (\S+) (\S+) (\S+) \S+', line)
        if match:
            try:
                type_string = type_strings[match.group(3)] + " " + sub_type_strings[match.group(4)]
            except KeyError:
                type_string = match.group(3) + " " + match.group(4)
            output = [match.group(1), match.group(2), type_string]
        return output

    def run(self):
        newline = ''
        if self.platform == "windows":
            newline = '\r\n'
        else:
            newline = '\n'

        cscope_arg_list = ['toks', '-i', self.database, '--id', self.symbol]
        if self.mode != "any":
            cscope_arg_list.append('--' + str(self.mode))
        popen_arg_list = {
            "shell": False,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE
        }
        if (self.platform == "windows"):
            popen_arg_list["creationflags"] = 0x08000000

        proc = subprocess.Popen(cscope_arg_list, **popen_arg_list)
        output = proc.communicate()[0].decode("utf-8").split(newline)
        # print(output)

        self.matches = []
        self.light_matches = []
        for line in output:
            match = self.match_output_line(line)
            if match != None:
                self.matches.append(match)
                self.light_matches.append(match[0] + " <" + match[1] + ">")
                # print "File ", match.group(1), ", Line ", match.group(2), ", Instance ", match.group(3)

class ToksCommand(sublime_plugin.TextCommand):
    _backLines = []
    _forwardLines = []
    pre_lookup_position = None

    @staticmethod
    def is_history_empty():
        return len(ToksCommand._backLines) == 0

    @staticmethod
    def is_future_empty():
        return len(ToksCommand._forwardLines) == 0

    @staticmethod
    def navigate_back(view):
        if not ToksCommand.is_history_empty():
            current_position = getCurrentPosition(view)
            if ToksCommand.is_future_empty() or not isOnSameLine(ToksCommand._forwardLines[0], current_position):
                ToksCommand._forwardLines.insert(0, current_position)
            while len(ToksCommand._backLines) > 1 and isOnSameLine(ToksCommand._backLines[0], current_position):
                ToksCommand._backLines = ToksCommand._backLines[1:]
            if not ToksCommand.is_history_empty():
                encoded_position = ToksCommand._backLines[0]
                sublime.active_window().open_file(encoded_position, sublime.ENCODED_POSITION)
                while len(ToksCommand._forwardLines) > 1 and isOnSameLine(ToksCommand._forwardLines[0], encoded_position):
                    ToksCommand._forwardLines = ToksCommand._forwardLines[1:]

    @staticmethod
    def navigate_forward(view):
        if not ToksCommand.is_future_empty():
            encoded_position = ToksCommand._forwardLines[0]
            ToksCommand._forwardLines = ToksCommand._forwardLines[1:]
            current_position = getCurrentPosition(view)
            if ToksCommand.is_history_empty() or not isOnSameLine(ToksCommand._backLines[0], current_position):
                ToksCommand._backLines.insert(0, current_position)
            if ToksCommand.is_history_empty() or not isOnSameLine(ToksCommand._backLines[0], encoded_position):
                ToksCommand._backLines.insert(0, encoded_position)
            sublime.active_window().open_file(encoded_position, sublime.ENCODED_POSITION)

    @staticmethod
    def navigate_jump(view, source, destination):
        if ToksCommand.is_history_empty() or not isOnSameLine(ToksCommand._backLines[0], source):
            ToksCommand._backLines.insert(0, source)
        if ToksCommand.is_history_empty() or not isOnSameLine(ToksCommand._backLines[0], destination):
            ToksCommand._backLines.insert(0, destination)
        ToksCommand._forwardLines = []
        sublime.active_window().open_file(destination, sublime.ENCODED_POSITION)

    def __init__(self, view):
        self.view = view
        self.database = None
        settings = get_settings()

    def look_for_database(self):
        pdirs = sublime.active_window().folders()
        for directory in pdirs:
            if ("TOKS" in os.listdir(directory)):
                return directory
            if (len(pdirs) > 0):
                return sublime.active_window().folders()[0]

    def on_select(self, index):
        if index != -1:
            destination = os.path.join(self.root, self.worker.matches[index][0])
            self.navigate_jump(self.view, self.pre_lookup_position, destination)
        else:
            sublime.active_window().open_file(self.pre_lookup_position, sublime.ENCODED_POSITION)

    def on_highlighted(self, index):
        destination = os.path.join(self.root, self.worker.matches[index][0])
        sublime.active_window().open_file(destination, sublime.ENCODED_POSITION | sublime.TRANSIENT)

    def update_status(self, worker, message, complete, count=0, dir=1):
        if self.worker == worker:
            if worker.is_alive():
                count = count + dir
                if count == 7:
                    dir = -1
                elif count == 0:
                    dir = 1
                self.view.set_status("SublimeToks", message + " [%s=%s]" %
                                    (' ' * count, ' ' * (7 - count)))
                sublime.set_timeout(lambda: self.update_status(worker, message, complete, count, dir), 100)
            else:
                self.view.erase_status("SublimeToks")
                complete()

    def run(self, edit, mode):
        self.mode = mode

        # Cancel any running worker
        self.worker = None

        # Look for database
        if self.database == None:
            self.root = self.look_for_database()
            if self.root == None:
                sublime.error_message("SublimeToks: Please add at least one directory to the project to enable indexing")
                return
            self.database = os.path.join(self.root, "TOKS")

        # Check if database exists
        if not "TOKS" in os.listdir(self.root) or self.mode == "index":
            self.worker = SublimeToksIndexer(self.root)
            self.worker.start()
            self.update_status(self.worker, "Indexing", self.on_indexing_complete)
            return

        self.on_indexing_complete()

    def on_indexing_complete(self):

        if self.mode == "index":
            return

        # Save the pre lookup position
        self.pre_lookup_position = getCurrentPosition(self.view)

        # Search for the first word that is selected.
        first_selection = self.view.word(self.view.sel()[0])
        self.symbol = self.view.substr(first_selection)

        # Show only the one selection picked for search
        self.view.sel().clear()
        self.view.sel().add(first_selection)

        if get_setting("prompt_before_searching") == True:
            sublime.active_window().show_input_panel('Toks Symbol To Search:',
                                                     self.symbol,
                                                     self.on_search_confirmed,
                                                     None,
                                                     None)
        else:
            self.on_search_confirmed(self.symbol)

    def on_search_confirmed(self, symbol):
        self.symbol = symbol
        self.worker = SublimeToksSearcher(
                view = self.view,
                platform = sublime.platform(),
                root = self.root,
                database = self.database,
                symbol = symbol,
                mode = self.mode)
        self.worker.start()
        self.update_status(self.worker, "Searching", self.on_lookup_complete)

    def on_lookup_complete(self):
        #self.view.show_popup_menu(self.worker.light_matches, self.on_select)
        sublime.active_window().show_quick_panel(self.worker.matches, self.on_select, 0, 0, self.on_highlighted)
