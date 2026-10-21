# Metal vs Vulkan (MoltenVK) CPU-time benchmark for NRISamples

The 'benchmark.py' file measures how much CPU time one frame takes when an NRISamples sample runs on Metal/Vulkan. This is the measurement script for objective 4 of our ENSC 461/894 project. The folder contains the script only, not the results (as of right now).


## What it measures

For every (sample, API) pair and repetition, the script runs the sample twice. One run is short (300 frames), and the other is long (2000 frames). It reads the CPU time the OS gave to the child process (user + system time) and also the wall clock time of each run. The formula below cancels the one time startup cost so that it is not included in the analysis.

cost per frame = (long run - short run) / (long frames - short frames)

This number is the CPU time of the whole process per frame; not just encode and submit. This would need a timer inside the frame loop of NRIFramework.


## Requirements

- running macOS (tested on a MacBook Air, Apple M2).
- Python 3.9 or newer (tested on 3.9.6)
- NRISamples built in the Release configuration with Metal support, so that '_Bin/Release/Triangle' and '_Bin/Release/SceneViewer' exist.
- For the Vulkan runs, the Vulkan SDK, loaded in the same shell with 'source ~/VulkanSDK/<version>/setup-env.sh'


## How to run

From the NRISamples root, in a shell where the Vulkan SDK is loaded:
python3 Scripts/Benchmark/benchmark.py

A quick test run:
python3 Scripts/Benchmark/benchmark.py --samples Triangle --reps 2 --short 100 --long 400

Run 'python3 Scripts/Benchmark/benchmark.py --help' for all options.

Before a real run:

1. Plug the Mac in. Right now, I have the script refusing to start on battery power and only on AC power. Not sure if we still need this but I thought running on battery power was messing up my results. Might just be a my laptop specific thing though.
2. Quit other apps and keep the windows uncovered while it runs.
3. Check that the machine is quiet. Background jobs like spotlight indexing or photos analysis can use a whole CPU core. I used this command to check this: 'top -l 2 -o cpu -n 5 -stats pid,command,cpu | tail -7'


## What the script does on every run

- Deletes 'pso_cache.bin' first. Metal and Vulkan write the same file name, so without this a run could read the other backend's cache.
- Passes '--alwaysActive'. Without it, the frame loop stalls when the window is not focused.
- Leaves vsync off (the sample default).
- Runs one discarded warm up per pair, then interleaves the APIs inside each repetition so slow drift (heat, background load) affects both the same way.

A run is marked INVALID and excluded if:
- the exit code is not 0
- "Shutting down" was not printed 
- a Vulkan run printed "Validation Enabled" (the validation layer inflates CPU time)


## Vulkan validation must be off

Installing the Vulkan SDK on my machine also created '~/.local/share/vulkan/loader_settings.d/vk_loader_settings.json', which sets 'VK_LAYER_KHRONOS_validation' to "control": "on". That forces the validation layer on for every Vulkan program. With it on, the Vulkan runs print "Validation Enabled" and it gets aborted


## Output

Each run writes two files to 'Scripts/Benchmark/results/' (ignored by git):
- 'raw-<timestamp>.csv': every run, with wall time, CPU time, exit code and validity.
- 'summary-<timestamp>.txt': machine info, git revisions, and the median, min, max, standard deviation and interquartile range of the per frame cost, in milliseconds, for CPU and wall time.


## Limits

- In the first session, the first seven repetitions came out lower than every later session, and I do not know why. Repeat the measurement in more than one session before trusting a comparison.


## AI assistance

Some parts of this script were written with help from Claude, but the logic for each line of code has been understood. The script was run and checked on the Arsh's machine.
