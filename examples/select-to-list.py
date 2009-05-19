# Exercise 2 from http://webapp.dam.brown.edu/wiki/SciComp/CudaExercises

# Generate an array of random numbers between 0 and 1
# List the indices of those numbers that are greater than a given limit

from __future__ import division
import pycuda.driver as cuda
import pycuda.autoinit
import pycuda.gpuarray as gpuarray
from pycuda.compiler import SourceModule

import numpy


# Define block size and number of elements per thread

block_size = 512
el_per_thread = 1
# !!! program only works for el_per_thread = 1            !!!
# !!! otherwise the for-loops in the kernel cause a crash !!!
multiple_block_size = el_per_thread * block_size


# Create an array of random numbers and set limit

amount = 256*2560
limit = 0.9
assert amount % multiple_block_size == 0
a = numpy.random.rand(amount)
a = a.astype(numpy.float32)
a_gpu = gpuarray.to_gpu(a)


# Initialize array for the selection on device

selec = numpy.zeros_like(a)
selec = selec.astype(numpy.int32)
selec.fill(-1)
selec_gpu = gpuarray.to_gpu(selec)


# Initialize a counter on device

counter = numpy.zeros(1)
counter = counter.astype(numpy.int32)
counter_gpu = cuda.mem_alloc(counter.nbytes)
cuda.memcpy_htod(counter_gpu, counter)


# Computation on device

mod = SourceModule("""
#define BLOCK_SIZE %(block_size)d
#define EL_PER_THREAD %(el_per_thread)d

__global__ void select_them(float *a, int *selec, float limit, int *counter)
{
    __shared__ int selec_smem[EL_PER_THREAD * BLOCK_SIZE];
    __shared__ int counter_smem;
    __shared__ int *counter_smem_ptr;

    int jump = 16;
    int idx = EL_PER_THREAD * blockIdx.x * BLOCK_SIZE + threadIdx.x + 
              (EL_PER_THREAD - 1) * (threadIdx.x / 16) * jump;

    if (threadIdx.x == 1)
    {
        counter_smem_ptr = &counter_smem;
        counter_smem = 0;
    }

    #if EL_PER_THREAD == 1
        selec_smem[threadIdx.x] = -1;
    #else
        for (int i = 0; i <= EL_PER_THREAD - 1; i++)
            selec_smem[threadIdx.x + i * BLOCK_SIZE] = -1;
    #endif

    __syncthreads();

   // each counting thread writes its index to shared memory

    #if EL_PER_THREAD == 1
        if (a[idx] >= limit)
            selec_smem[atomicAdd(counter_smem_ptr, 1)] = idx;
    #else
         for (int i = 0; i <= EL_PER_THREAD - 1; i++)
         {
             if (a[idx + i * jump] >= limit)
                 selec_smem[atomicAdd(counter_smem_ptr, 1)] = idx + i * jump;
         }
    #endif

    __syncthreads();

    if (threadIdx.x == 1)
        counter_smem = atomicAdd(counter, counter_smem);

    __syncthreads();

    #if EL_PER_THREAD == 1
        if (selec_smem[threadIdx.x] >= 0)
            selec[counter_smem + threadIdx.x] = selec_smem[threadIdx.x];
    #else
        for (int i = 0; i <= EL_PER_THREAD - 1; i++)
        {
            if (selec_smem[threadIdx.x + i * jump] >= 0)
                selec[counter_smem + threadIdx.x + i * jump] = 
                selec_smem[threadIdx.x + i * jump];
        }
    #endif
}
""" % {"block_size": block_size, "el_per_thread": el_per_thread})


# Prepare function call

func = mod.get_function("select_them")
func.prepare("PPfP", block=(block_size, 1, 1))


# Prepare getting the time

start = cuda.Event()
stop = cuda.Event()


# Call function and get time

cuda.Context.synchronize()
start.record()
func.prepared_call((amount // multiple_block_size, 1),
                   a_gpu.gpudata, selec_gpu.gpudata, limit, counter_gpu)
stop.record()


# Copy selection from device to host

selec_gpu.get(selec)

stop.synchronize()


# Evaluate memory bandwidth and verify solution

elems_in_selec = 0
for i in range(0, amount):
    if selec[i] >= 0:
        elems_in_selec = elems_in_selec + 1

elapsed_seconds = stop.time_since(start) * 1e-3
print "mem bw:", (a.nbytes + elems_in_selec * 4) / elapsed_seconds / 1e9

numpy.set_printoptions(threshold=2000)

filtered_set = sorted(list(item for item in selec if item != -1))
reference_set = sorted(list(i for i, x in enumerate(a) if x>limit))
assert filtered_set == reference_set
