#!/usr/bin/env python

"""
Runs MPAS-Analysis via a configuration file (e.g. `config.analysis`)
specifying analysis options.

Authors
-------
Xylar Asay-Davis, Phillip J. Wolfram
"""

import os
import matplotlib as mpl
import argparse
import traceback
import sys
import warnings
import subprocess
import time
import pkg_resources

from mpas_analysis.configuration import MpasAnalysisConfigParser

from mpas_analysis.shared.io.utility import build_config_full_path, \
    make_directories

from mpas_analysis.shared.html import generate_html


def update_generate(config, generate):  # {{{
    """
    Update the 'generate' config option using a string from the command line.

    Parameters
    ----------
    config : ``MpasAnalysisConfigParser`` object
        contains config options

    generate : str
        a comma-separated string of generate flags: either names of analysis
        tasks or commands of the form ``all_<tag>`` or ``no_<tag>`` indicating
        that analysis with a given tag should be included or excluded).

    Authors
    -------
    Xylar Asay-Davis
    """

    # overwrite the 'generate' in config with a string that parses to
    # a list of string
    generateList = generate.split(',')
    generateString = ', '.join(["'{}'".format(element)
                                for element in generateList])
    generateString = '[{}]'.format(generateString)
    config.set('output', 'generate', generateString)  # }}}


def run_parallel_tasks(config, analyses, configFiles, taskCount):
    # {{{
    """
    Launch new processes for parallel tasks, allowing up to ``taskCount``
    tasks to run at once.

    Parameters
    ----------
    config : ``MpasAnalysisConfigParser`` object
        contains config options

    analyses : list of ``AnalysisTask`` objects
        A list of analysis tasks to run

    configFiles : list of str
        A list of config files, passed on to each parallel task

    taskCount : int
        The maximum number of tasks that are allowed to run at once

    Authors
    -------
    Xylar Asay-Davis
    """

    taskNames = [analysisTask.taskName for analysisTask in analyses]

    taskCount = min(taskCount, len(taskNames))

    (processes, logs) = launch_tasks(taskNames[0:taskCount], config,
                                     configFiles)
    remainingTasks = taskNames[taskCount:]
    tasksWithErrors = []
    while len(processes) > 0:
        (taskName, process) = wait_for_task(processes)
        if process.returncode == 0:
            print "Task {} has finished successfully.".format(taskName)
        else:
            print "ERROR in task {}.  See log file {} for details".format(
                taskName, logs[taskName].name)
            tasksWithErrors.append(taskName)
        logs[taskName].close()
        # remove the process from the process dictionary (no need to bother)
        processes.pop(taskName)

        if len(remainingTasks) > 0:
            (process, log) = launch_tasks(remainingTasks[0:1], config,
                                          configFiles)
            # merge the new process and log into these dictionaries
            processes.update(process)
            logs.update(log)
            remainingTasks = remainingTasks[1:]

    # raise the last exception so the process exits with an error
    errorCount = len(tasksWithErrors)
    if errorCount == 1:
        print "There were errors in task {}".format(tasksWithErrors[0])
        sys.exit(1)
    elif errorCount > 0:
        print "There were errors in {} tasks: {}".format(
                errorCount, ', '.join(tasksWithErrors))
        sys.exit(1)
    # }}}


def launch_tasks(taskNames, config, configFiles):  # {{{
    """
    Launch one or more tasks

    Parameters
    ----------
    taskNames : list of str
        the names of the tasks to launch

    config : ``MpasAnalysisConfigParser`` object
        contains config options

    configFiles : list of str
        A list of config files, passed along when each task is launched

    Authors
    -------
    Xylar Asay-Davis
    """
    thisFile = os.path.realpath(__file__)

    commandPrefix = config.getWithDefault('execute', 'commandPrefix',
                                          default='')
    if commandPrefix == '':
        commandPrefix = []
    else:
        commandPrefix = commandPrefix.split(' ')

    processes = {}
    logs = {}
    for taskName in taskNames:
        args = commandPrefix + \
            [thisFile, '--subtask', '--generate', taskName] + configFiles

        logFileName = '{}/{}.log'.format(logsDirectory, taskName)

        # write the command to the log file
        logFile = open(logFileName, 'w')
        logFile.write('Command: {}\n'.format(' '.join(args)))
        # make sure the command gets written before the rest of the log
        logFile.flush()
        print 'Running {}'.format(taskName)
        process = subprocess.Popen(args, stdout=logFile,
                                   stderr=subprocess.STDOUT)
        processes[taskName] = process
        logs[taskName] = logFile

    return (processes, logs)  # }}}


def wait_for_task(processes):  # {{{
    """
    Wait for the next process to finish and check its status.  Returns both the
    task name and the process that finished.

    Parameters
    ----------
    processes : list of ``subprocess.Popen`` objects
        Processes to wait for


    Returns
    -------
    taskName : str
        The name of the task that finished

    process : ``subprocess.Popen`` object
        The process that finished

    Authors
    -------
    Xylar Asay-Davis
    """

    # first, check if any process has already finished
    for taskName, process in processes.iteritems():  # python 2.7!
        if(not is_running(process)):
            return (taskName, process)

    # No process has already finished, so wait for the next one
    (pid, status) = os.waitpid(-1, 0)
    for taskName, process in processes.iteritems():
        if pid == process.pid:
            process.returncode = status
            # since we used waitpid, this won't happen automatically
            return (taskName, process)  # }}}


def is_running(process):  # {{{
    """
    Returns whether a given process is currently running

    Parameters
    ----------
    process : ``subprocess.Popen`` object
        The process to check

    Returns
    -------
    isRunning : bool
        whether the process is running

    Authors
    -------
    Xylar Asay-Davis
    """

    try:
        os.kill(process.pid, 0)
    except OSError:
        return False
    else:
        return True  # }}}


def build_analysis_list(config):  # {{{
    """
    Build a list of analysis modules based on the 'generate' config option.
    New tasks should be added here, following the approach used for existing
    analysis tasks.

    Parameters
    ----------
    config : ``MpasAnalysisConfigParser`` object
        contains config options

    Returns
    -------
    analysesToGenerate : list of ``AnalysisTask`` objects
        A list of analysis tasks to run

    Authors
    -------
    Xylar Asay-Davis
    """

    # choose the right rendering backend, depending on whether we're displaying
    # to the screen
    if not config.getboolean('plot', 'displayToScreen'):
        mpl.use('Agg')

    # analysis can only be imported after the right MPL renderer is selected
    from mpas_analysis import ocean
    from mpas_analysis import sea_ice

    # analyses will be a list of analysis classes
    analyses = []

    # Ocean Analyses

    analyses.append(ocean.ClimatologyMapMLD(config))
    analyses.append(ocean.ClimatologyMapSST(config))
    analyses.append(ocean.ClimatologyMapSSS(config))
    analyses.append(ocean.TimeSeriesOHC(config))
    analyses.append(ocean.TimeSeriesSST(config))
    analyses.append(ocean.MeridionalHeatTransport(config))
    analyses.append(ocean.StreamfunctionMOC(config))
    analyses.append(ocean.IndexNino34(config))

    # Sea Ice Analyses
    analyses.append(sea_ice.ClimatologyMapSeaIceConc(config, hemisphere='NH'))
    analyses.append(sea_ice.ClimatologyMapSeaIceThick(config, hemisphere='NH'))
    analyses.append(sea_ice.ClimatologyMapSeaIceConc(config, hemisphere='SH'))
    analyses.append(sea_ice.ClimatologyMapSeaIceThick(config, hemisphere='SH'))
    analyses.append(sea_ice.TimeSeriesSeaIce(config))

    # check which analysis we actually want to generate and only keep those
    analysesToGenerate = []
    for analysisTask in analyses:
        # for each anlaysis module, check if we want to generate this task
        # and if the analysis task has a valid configuration
        if analysisTask.check_generate():
            add = False
            try:
                analysisTask.setup_and_check()
                add = True
            except (Exception, BaseException):
                traceback.print_exc(file=sys.stdout)
                print "ERROR: analysis module {} failed during check and " \
                    "will not be run".format(analysisTask.taskName)
            if add:
                analysesToGenerate.append(analysisTask)

    return analysesToGenerate  # }}}


def run_analysis(config, analyses):  # {{{
    """
    Run one or more analysis tasks

    Parameters
    ----------
    config : ``MpasAnalysisConfigParser`` object
        contains config options

    analyses : list of ``AnalysisTask`` objects
        A list of analysis tasks to run

    Raises
    ------
    Exception:
        If one or more tasks raise exceptions, re-raises the last exception
        after all tasks have completed to indicate that there was a problem

    Authors
    -------
    Xylar Asay-Davis
    """

    # run each analysis task
    tasksWithErrors = []
    lastStacktrace = None
    for analysisTask in analyses:
        # write out a copy of the configuration to document the run
        logsDirectory = build_config_full_path(config, 'output',
                                               'logsSubdirectory')
        try:
            startTime = time.clock()
            analysisTask.run()
            runDuration = time.clock() - startTime
            m, s = divmod(runDuration, 60)
            h, m = divmod(int(m), 60)
            print 'Execution time: {}:{:02d}:{:05.2f}'.format(h, m, s)
        except (Exception, BaseException) as e:
            if isinstance(e, KeyboardInterrupt):
                raise e
            lastStacktrace = traceback.format_exc()
            print "ERROR: analysis task {} failed during run".format(
                analysisTask.taskName)
            print lastStacktrace
            tasksWithErrors.append(analysisTask.taskName)

        configFileName = '{}/configs/config.{}'.format(logsDirectory,
                                                       analysisTask.taskName)
        configFile = open(configFileName, 'w')
        config.write(configFile)
        configFile.close()

    if config.getboolean('plot', 'displayToScreen'):
        import matplotlib.pyplot as plt
        plt.show()

    # raise the last exception so the process exits with an error
    errorCount = len(tasksWithErrors)
    if errorCount == 1:
        if len(analyses) > 1:
            print "There were errors in task {}".format(tasksWithErrors[0])
            print "The stacktrace was:"
            print lastStacktrace
        sys.exit(1)
    elif errorCount > 0:
        print "There were errors in {} tasks: {}".format(
                errorCount, ', '.join(tasksWithErrors))
        print "The last stacktrace was:"
        print lastStacktrace
        sys.exit(1)

    # }}}


if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--subtask", dest="subtask", action='store_true',
                        help="If this is a subtask when running parallel "
                             "tasks")
    parser.add_argument("-g", "--generate", dest="generate",
                        help="A list of analysis modules to generate "
                        "(nearly identical generate option in config file).",
                        metavar="ANALYSIS1[,ANALYSIS2,ANALYSIS3,...]")
    parser.add_argument('configFiles', metavar='CONFIG',
                        type=str, nargs='+', help='config file')
    args = parser.parse_args()

    # add config.default to cover default not included in the config files
    # provided on the command line
    if pkg_resources.resource_exists('mpas_analysis', 'config.default'):
        defaultConfig = pkg_resources.resource_filename('mpas_analysis',
                                                        'config.default')
        configFiles = [defaultConfig] + args.configFiles
    else:
        print 'WARNING: Did not find config.default.  Assuming other config ' \
              'file(s) contain a\n' \
              'full set of configuration options.'
        configFiles = args.configFiles

    config = MpasAnalysisConfigParser()
    config.read(configFiles)

    if args.generate:
        update_generate(config, args.generate)

    logsDirectory = build_config_full_path(config, 'output',
                                           'logsSubdirectory')
    make_directories(logsDirectory)
    make_directories('{}/configs/'.format(logsDirectory))

    analyses = build_analysis_list(config)

    parallelTaskCount = config.getWithDefault('execute', 'parallelTaskCount',
                                              default=1)

    if parallelTaskCount <= 1 or len(analyses) == 1:
        run_analysis(config, analyses)
    else:
        run_parallel_tasks(config, analyses, configFiles, parallelTaskCount)

    if not args.subtask:
        generate_html(config, analyses)

# vim: foldmethod=marker ai ts=4 sts=4 et sw=4 ft=python
