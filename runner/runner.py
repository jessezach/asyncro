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
        curdir = os.getcwd()

        if os.path.exists(curdir + '/' + results_folder):
            shutil.rmtree(curdir + '/' + results_folder)

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
        copy_all_screenshots(suites, results_folder)
        merge_results(suites, test_folder, results_folder)
    else:
        raise ValueError('No test folder provided')


def initiate_dry_run(command):
    FNULL = open(os.devnull, 'w')
    curdir = os.getcwd()
    subprocess.call("pybot --dryrun --output=%s/suites.xml --report=NONE --log=NONE %s"
                    % (curdir, command), stdout=FNULL, stderr=subprocess.STDOUT, shell=True)
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


def merge_results(suites, test_folder, results_folder):
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
    suite, folder_name, command, results_folder = args
    curdir = os.getcwd()
    test_path = suite.replace((curdir + '/'), '')
    folder = string.replace(test_path, '/', '.')
    output_path = curdir + '/' + results_folder + '/' + folder
    process = subprocess.Popen('pybot --outputdir=%s --output=result.xml --report=NONE --log=NONE %s %s'
                               % (output_path, command, suite), stdout=subprocess.PIPE,
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
    for i in range(0, len(options)):
        if options[i].startswith('--outputdir'):
            return True, i
    return False, None


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
            src_path = output_path + '/' + fname
            shutil.copyfile(src_path, (curdir + '/' + results_folder +
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
