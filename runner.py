import sys, string, os, time
import subprocess
import xml.etree.ElementTree as ET
import multiprocessing
import signal
import shutil


CTRL_C_PRESSED = False


def parse_args(args):
    options = args
    test_folder = args.pop()

    if not 'test' in test_folder.lower():
        raise ValueError('Tests path not provided')

    has_result_path = has_results_folder(options)

    if '-d' in options:
        ind = options.index('-d')
        options.pop(ind)
        results_folder = options.pop(ind)
    elif has_result_path[0]:
        ind = has_result_path[1]
        folder_parts = options[ind].partition('=')
        results_folder = folder_parts[2]
        options.pop(ind)
    else:
        results_folder = 'results'

    processes = max(multiprocessing.cpu_count(), 2)
    if options[0].startswith('--n'):
        process_parts = options[0].partition('=')
        if process_parts[2]:
            processes = int(process_parts[2])
        options.pop(0)

    command = options + [test_folder]
    options = ' '.join(options)
    command = ' '.join(command)
    return command, options, test_folder, results_folder, processes


def run_tests(args):
    command, options, test_folder, results_folder, processes = parse_args(args)
    if command:
        suites = initiate_dry_run(command)
        original_signal_handler = signal.signal(signal.SIGINT, keyboard_interrupt)
        pool = multiprocessing.Pool(processes=processes)
        result = pool.map_async(execute_test, ((suite, test_folder, options, results_folder)
                                               for suite in suites))
        pool.close()
        while not result.ready():
            try:
                time.sleep(0.1)
            except IOError:
                keyboard_interrupt()
        signal.signal(signal.SIGINT, original_signal_handler)
        # copy_all_screenshots(suites, test_folder, results_folder)
        merge_results(suites, test_folder, results_folder)
    else:
        raise ValueError('No test folder provided')


def initiate_dry_run(command):
    FNULL = open(os.devnull, 'w')
    subprocess.call("pybot --dryrun --output=suites.xml --report=NONE --log=NONE %s"
                    % command, stdout=FNULL, stderr=subprocess.STDOUT, shell=True)
    tree = ET.parse('suites.xml')
    root = tree.getroot()
    suites = []
    for suite in root.iter('suite'):
        attrs = suite.attrib
        if 'source' in attrs:
            path = attrs['source']
            if '.robot' in path:
                suites.append(path)
    os.remove('suites.xml')
    return suites


def merge_results(suites, test_folder, results_folder):
    for i in range(len(suites)):
        suite = suites[i]
        index = suite.rfind(test_folder)
        new_suite = suite[:index]
        test_path = suite[index:]
        folder = string.replace(test_path, '/', '.')
        suites[i] = new_suite + results_folder + '/' + folder + '/result.xml'
        output_directory = new_suite + results_folder
    subprocess.call('rebot --outputdir=%s --name=Tests --output output.xml %s'
                    % (output_directory, ' '.join(suites)), shell=True)


def execute_test(args):
    global CTRL_C_PRESSED
    if CTRL_C_PRESSED:
        # Keyboard interrupt has happened!
        return
    path, folder_name, command, results_folder = args
    index = path.rfind(folder_name)
    new_path = path[:index]
    test_path = path[index:]
    folder = string.replace(test_path, '/', '.')
    output_path = new_path + results_folder + '/' + folder
    process = subprocess.Popen('pybot --outputdir=%s --output=result.xml --report=NONE --log=NONE %s %s'
                               % (output_path, command, path), stdout=subprocess.PIPE,
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


def has_results_folder(options):
    for option in options:
        if option.startswith('--outputdir'):
            location = options.index(option)
            return True, location
    return False, None


def copy_all_screenshots(suites, test_folder, results_folder):
    count = 1
    for i in range(len(suites)):
        suite = suites[i]
        index = suite.rfind(test_folder)
        new_suite = suite[:index]
        test_path = suite[index:]
        folder = string.replace(test_path, '/', '.')
        pabot_dir = new_suite + results_folder + '/' + folder
        for root, dirs, files in os.walk(pabot_dir):
            for fname in files:
                if fname.endswith('.png'):
                    abs_path = os.path.join(root, fname)
                    shutil.copyfile(abs_path, (new_suite + results_folder +
                                               '/' + 'selenium-screenshot-' + str(count) + '.png'))
                    count += 1


if __name__ == '__main__':
    run_tests(sys.argv[1:])
