import sys, string, os, time
import subprocess
import xml.etree.ElementTree as ET
import multiprocessing
import signal
import shutil
from robot.run import USAGE
from robot.utils import ArgumentParser

CTRL_C_PRESSED = False


def parse_args(args):
    options = args
    processes = max(multiprocessing.cpu_count(), 2)

    if options[0].startswith('--n'):
        process_parts = options[0].partition('=')
        if process_parts[2]:
            processes = int(process_parts[2])
        options = options[1:]

    opts, datasources = ArgumentParser(USAGE,
                           auto_pythonpath=False,
                           auto_argumentfile=False,
                           env_options='ROBOT_OPTIONS').\
        parse_args(options)
    keys = set()
    for k in opts:
        if opts[k] is None:
            keys.add(k)

    for k in keys:
        del opts[k]
    return opts, datasources, processes


def run_tests(args):
    options, datasources, processes = parse_args(args)

    if 'rerunfailed'not in options:

        if 'outputdir' not in options:
            results_folder = 'results'
        else:
            results_folder = get_results_folder(options['outputdir'])
            del options['outputdir']

        suites = initiate_dry_run(options, datasources)
        original_signal_handler = signal.signal(signal.SIGINT, keyboard_interrupt)
        pool = multiprocessing.Pool(processes=processes)
        result = pool.map_async(execute_test, ((suite, options, results_folder)
                                               for suite in suites))
        pool.close()
        while not result.ready():
            try:
                time.sleep(0.1)
            except IOError:
                keyboard_interrupt()
        signal.signal(signal.SIGINT, original_signal_handler)
        copy_all_screenshots(suites, results_folder)
        merge_results(suites, results_folder)
    else:
        print 'Support for rerun failed has not been added yet..'


def get_results_folder(outputdir):
    if outputdir.endswith('.xml'):
        end_index = outputdir.rfind('/')
        return outputdir[:end_index]
    return outputdir


def initiate_dry_run(options, datasources):
    FNULL = open(os.devnull, 'w')
    curdir = os.getcwd()
    res = _options_to_cli_arguments(options)
    datasources = [d.encode('utf-8') if isinstance(d, unicode) else d
                   for d in datasources]

    subprocess.call("pybot --dryrun --output=%s/suites.xml --report=NONE --log=NONE %s %s"
                    % (curdir, ' '.join(res), ' '.join(datasources)),
                    stdout=FNULL, stderr=subprocess.STDOUT, shell=True)
    tree = ET.parse(curdir + '/suites.xml')
    root = tree.getroot()
    suites = []
    for suite in root.iter('suite'):
        attrs = suite.attrib
        if 'source' in attrs:
            path = attrs['source']
            if '.robot' in path:
                suites.append(path)
    os.remove(curdir + '/suites.xml')
    return suites


def _options_to_cli_arguments(opts):
    res = []
    for k, v in opts.items():
        if isinstance(v, str):
            res += ['--' + str(k), str(v)]
        elif isinstance(v, unicode):
            res += ['--' + str(k), v.encode('utf-8')]
        elif isinstance(v, bool) and (v is True):
            res += ['--' + str(k)]
        elif isinstance(v, list):
            for value in v:
                if isinstance(value, unicode):
                    res += ['--' + str(k), value.encode('utf-8')]
                else:
                    res += ['--' + str(k), str(value)]
    return res


def merge_results(suites, results_folder):
    curdir = os.getcwd()
    for i in range(len(suites)):
        suite = suites[i]
        test_path = suite.replace((curdir + '/'), '')
        folder = string.replace(test_path, '/', '.')
        suites[i] = curdir + '/' + results_folder + '/' + folder + '/result.xml'
        output_directory = curdir + '/' + results_folder
    subprocess.call('rebot --outputdir=%s --name=Tests --output output.xml %s'
                    % (output_directory, ' '.join(suites)), shell=True)


def execute_test(args):
    global CTRL_C_PRESSED
    if CTRL_C_PRESSED:
        # Keyboard interrupt has happened!
        return
    suite, options, results_folder = args
    res = _options_to_cli_arguments(options)
    curdir = os.getcwd()
    test_path = suite.replace((curdir + '/'), '')
    folder = string.replace(test_path, '/', '.')
    output_path = curdir + '/' + results_folder + '/' + folder
    process = subprocess.Popen('pybot --outputdir=%s --output=result.xml --report=NONE --log=NONE %s %s'
                               % (output_path, ' '.join(res), suite), stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, shell=True)
    print 'Started [PID:%s] %s' % (process.pid, folder)
    rc = wait_for_result(process, folder)
    if rc != 0:
        print 'Failed! %s' % folder
    else:
        print 'Passed! %s' % folder


def wait_for_result(process, suite_name):
    rc = None
    elapsed = 0
    ping_time = ping_interval = 150
    while rc is None:
        rc = process.poll()
        time.sleep(0.1)
        elapsed += 1
        if elapsed == ping_time:
            ping_interval += 50
            ping_time += ping_interval
            print '[PID:%s] still running %s after %s seconds' \
                  % (process.pid, suite_name, elapsed / 10.0)
    return rc


def keyboard_interrupt(*args):
    global CTRL_C_PRESSED
    CTRL_C_PRESSED = True
    sys.exit()


def update_screenshot_and_report(output_path, folder, results_folder):
    tree = ET.parse(output_path + '/result.xml')
    root = tree.getroot()
    curdir = os.getcwd()

    for suite in root.iter('msg'):
        text = suite.text
        if text.startswith('</td></tr>') and 'img src' in text:
            old_image_path, new_image_path = get_href_attribute(text, folder)
            temp = text.replace(('<a href="%s">' % old_image_path),
                                ('<a href="%s">' % new_image_path))
            final = temp.replace(('<img src="%s" width="800px">' % old_image_path),
                                 ('<img src="%s" width="800px">' % new_image_path))
            suite.text = final
    tree.write(output_path + '/result.xml')

    for fname in os.listdir(output_path):
        if fname.endswith('.png'):
            abs_path = output_path + '/' + fname
            shutil.copyfile(abs_path, (curdir + '/' + results_folder +
                                       '/' + folder + '.' + fname))


def get_href_attribute(text, folder):
    ind = text.index('href')
    ind1 = text[ind:].index('>')
    href_text = text[ind:(ind+ind1)]
    href_text_parts = href_text.partition('=')
    old_image_path = href_text_parts[2]
    ind = old_image_path.index('"')
    ind1 = old_image_path.rfind('"')
    old_image_path = old_image_path[ind + 1:ind1]
    new_image_path = folder + '.' + old_image_path
    return old_image_path, new_image_path


def copy_all_screenshots(suites, results_folder):
    curdir = os.getcwd()
    for suite in suites:
        test_path = suite.replace((curdir + '/'), '')
        folder = test_path.replace('/', '.')
        output_path = curdir + '/' + results_folder + '/' + folder
        update_screenshot_and_report(output_path, folder, results_folder)


if __name__ == '__main__':
    run_tests(sys.argv[1:])
