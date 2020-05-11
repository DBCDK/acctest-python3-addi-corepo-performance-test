        #!/usr/bin/env python
# -*- coding: utf-8 -*-
# -*- mode: python -*-

import datetime
import logging
import os
from os.path import join
import re
import requests
import shutil
import sys
import time
import zipfile
import subprocess

from os_python.common.utils.init_functions import log_fields
from os_python.common.utils.init_functions import die
from os_python.common.utils.cleanupstack import CleanupStack

from os_python.docker.docker_container import DockerContainer
from os_python.docker.docker_container import ContainerSuitePool

from os_perftest.performance_test import PerformanceTest
from os_perftest.performance_test import NullHandler
import os_perftest.performance_plotter as performance_plotter
from os_perftest.utils import dump_statistics
from os_perftest.utils import format_traceback
from os_perftest.utils import test_executor
from os_perftest.utils import setup_logger


# define logger
logger = logging.getLogger("dbc." + __name__)
logger.addHandler(NullHandler())

class ContainerPoolImpl(ContainerSuitePool):

    def __init__(self):
        super(ContainerPoolImpl, self).__init__()

    def create_suite(self, suite):

        # corepo-data-snapshot-postgres-1.0-snapshot must be created and stored on the server that is used for performance test

        corepo_db = suite.create_container("corepo-db",
                                           image_name=self.cfg['snapshot-image'],
                                           start_timeout=1200)

        addi_db = suite.create_container("addi-db",
                                         image_name=DockerContainer.secure_docker_image('addi-service-postgres-1.0-snapshot'),
                                         start_timeout=1200)

        corepo_db.start()
        addi_db.start()
        addi_db.waitFor("database system is ready to accept connections")
        corepo_db.waitFor("database system is ready to accept connections")

        corepo_db_root = "corepo:corepo@%s:5432/corepo" % corepo_db.get_ip()


        addi_service = suite.create_container("addi-service",
                                              image_name=DockerContainer.secure_docker_image('addi-service-webapp-1.0-snapshot'),
                                              environment_variables={"COREPO_DATABASE": corepo_db_root,
                                                                     "ADDI_DATABASE": "addi:addi@%s:5432/addi" % addi_db.get_ip(),
                                                                     "THREAD_POOL_SIZE": self.cfg['number-of-threads'],
                                                                     "LOG__JavaScript_Logger": "INFO",
                                                                     "LOG__dk_dbc": "INFO",
                                                                     "JAVA_MAX_HEAP_SIZE": "4G",
                                                                     "PAYARA_STARTUP_TIMEOUT": 1200},
                                              start_timeout=1200)

        addi_service.start()
        addi_service.waitFor("was successfully deployed in")
        addi_service.waitFor(") ready in ")

def run_performance_test(configuration):
    """ Run the performance test """
    if not os.path.exists(configuration['log-folder']):
        os.mkdir(configuration['log-folder'])

    stop_stack = CleanupStack.getInstance()

    container_pool = ContainerPoolImpl()
    container_pool.cfg = configuration
    suite = container_pool.take(log_folder=configuration['log-folder'])
    stop_stack.addFunction(container_pool.shutdown)
    stop_stack.addFunction(container_pool.release, suite)

    addi_ip = suite.get("addi-service").get_ip()

    try:

        addi_jolokia_url = "http://%s:8080/jolokia" % suite.get("addi-service").get_ip()

        # Add jobs
        add_all_addi_job(addi_ip, "performance test job")

        test_executor(configuration['run-time'])

        dump_statistics(configuration['addi-metrics'], (addi_jolokia_url, 'AddiService'))

        # Automatically generated plot
        performance_plotter.plot_dump_to("performance-report-auto", configuration['addi-metrics'])
        # Plot based on hive-metrics.ini
        performance_plotter.plot('addi-metrics.ini', 'Addi service processing', 'performance-report')

    except Exception as err:
        die("Caught error during performance test:\n%s" % format_traceback(sys.exc_info(), err))

    finally:
        stop_stack.callFunctions()
        zip_logfiles(configuration['log-folder'], configuration['log-zip-file'])


# HELPER FUNCTIONS
def add_all_addi_job( addi_ip_address, tracking_id ):
        add_addi_url = "http://%s:8080/addAddiJobAllUnits" % addi_ip_address

        logger.info("Add all jobs to %s, tracking id:%s", add_addi_url, tracking_id)

        response = requests.post(add_addi_url)#, headers={'content-type':'text/xml;charset=UTF-8'}, data=content )
        if not response.ok:
            die("Add all jobs returned %s %s"%(response.status_code, response.reason))
        logger.debug("Responded: %s", response.text)

        return response.text


def delete_folders(*folders):
    """ delete folders if they exist """
    for folder in folders:
        if os.path.exists(folder):
            logger.debug("Deleting folder " + folder)
            shutil.rmtree(folder)


def format_traceback(exc_info, error):
    """ Formats traceback, for easy reading """
    import traceback
    exc_tb = traceback.extract_tb(exc_info[2])
    tb = traceback.format_list(exc_tb)
    tb = map(lambda x: [x], tb)

    formatted_traceback = []
    for entry in tb:
        for fentry in filter(lambda x: x != '', entry[0].split("\n")):
            formatted_traceback.append(fentry)

    formatted_traceback.insert(0, "Traceback (most recent call last):")
    formatted_traceback.append("%s: %s" % (error.__class__.__name__, str(error)))
    return "\n".join(formatted_traceback)


def zip_logfiles(logfolder, logzipfile):

    logger.info("Zipping log files")
    zfile = zipfile.ZipFile( os.path.abspath( logzipfile ), 'w', zipfile.ZIP_DEFLATED )
    for f in os.listdir( logfolder ):
        zfile.write( os.path.join(logfolder, f), f )
    zfile.close()
    #shutil.rmtree( logfolder )


def cli():
    """ Commandline interface
    """
    from optparse import OptionParser
    usage = "\nRun performance test of addi-corepo."

    parser = OptionParser(usage="%prog [options] jenkins_job_name build_number snapshot_image" + usage)

    parser.add_option("-r", "--run-time", action="store", type=int, dest="run_time", default=None,
                      help="Run time of test in seconds. Default is None (runs until ctrl-c is pressed)")

    parser.add_option("-t", "--threads", action="store", type=int, dest="threads", default=1,
                      help="Number of threads to search in. Default is 1")

    parser.add_option("-s", "--statistics-file", action="store", type="string", dest="stat_file", default='addi-corepo-performance-metrics.json',
                      help="Filename to use when dumping statistics. Default is 'addi-corepo-performance-metrics.json'")

    parser.add_option("-c", "--plot-config-file", action="store", type="string", dest="plot_config_file", default= 'addi-corepo-perftest.ini',
                      help="Config file to use when plotting statistics. Default is 'addi-corepo-perftest.ini'")

    parser.add_option("-v", "--verbose", action="store_true", dest="verbose",
                      help="verbose output")

    parser.add_option("-u", "--use-preloaded", action="store_true", dest="use_preloaded",
                      help="uses already downloaded artifacts")

    (options, args) = parser.parse_args()

    if len(args) < 3:
        parser.error("Mandatory arguments missing")

    return({'job-name': args[0],
            'build-number': int(args[1]),
            'snapshot-image': args[2],
            'run-time': options.run_time,
            'number-of-threads': options.threads,
            'statistics-file': os.path.join(options.stat_file),
            'plot-config-file': os.path.join(options.plot_config_file),
            'use-preloaded': options.use_preloaded,
            'verbose': options.verbose})

def main():
    """ Sets up configuration, secure resources and run the performance test
    """
    configuration = {'resource-folder': 'resources',
                     'build-folder': 'build',
                     'log-folder': 'logfiles',
                     'use-preloaded': False,
                     'addi-metrics': 'addi-metrics.json',
                     'jenkins': {'dependency-filename': 'dependencies.txt',
                                 'server': 'http://is.dbc.dk',
                                 'repository-project': 'opensearch-3rd-party-dependencies'},
                     'log-zip-file':'logs.zip'}
    configuration.update(cli())
    setup_logger(configuration['verbose'])
    run_performance_test(configuration)

main()
