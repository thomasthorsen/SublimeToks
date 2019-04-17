SublimeToks
===========

Easy to use source code navigation for C/C++ using ripgrep and toks as indexing backend.

Usage
=====

The only setup required is to create a project with at least one path for SublimeToks to know which files to search. Use any of the following lookup commands (also available from the command palette) to search for symbols and navigate to them:

 * ctrl-l + ctrl-s : Lookup all locations of a symbol
 * ctrl-l + ctrl-d : Lookup only definitions of a symbol
 * ctrl-l + ctrl-e : Lookup only declarations of a symbol
 * ctrl-l + ctrl-r : Lookup only references to a symbol

When using any of the lookup commands, the results will be presented in a quick panel with 3 lines of information for each result:

 # The filename, line and column of the result
 # The scope of the result
 # The classification of the result

When browsing through the results in the quick panel the file contents will be previewed in the active view. To cancel the lookup, press escape and the active view will go back to where you were. Press enter on a result and SublimeToks will navigate to the chosen location, saving the previous location in the history. To go back and forward in the history, use the following shortcuts:

 * ctrl-, Go back
 * ctrl-. Go forward

Note that if you move the caret away from a location in the history and then navigate back or forward, the new location will be included in the history. This is to make it easy to go back or forward in the history to check some details and then return to the point of development.

Installation
============

Install in the standard way using Package Control. If you are using Windows or Linux 64bit the plugin comes preloaded with the ripgrep and toks binaries needed for the indexing. If you are using Linux 32bit or Mac OS X you will need to install ripgrep and build toks from source and put it in your path to be able to use this plugin, see instructions at http://www.github.com/thomasthorsen/toks.
