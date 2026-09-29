"""Real CUDA driver computation probe; runs inside the container, no pip/toolkit.

Uses the installed Python stdlib and host-provided CUDA driver to JIT a tiny PTX
kernel, execute it, and check its output. This is testing code, not product code.
"""
import ctypes as c
import json

lib = c.CDLL('libcuda.so.1')

def call(name, *args):
    code = getattr(lib, name)(*args)
    if code:
        raise RuntimeError('%s: CUDA error %s' % (name, code))

call('cuInit', 0)
count = c.c_int()
call('cuDeviceGetCount', c.byref(count))
assert count.value > 0
context = c.c_void_p()
# CUDA 13 exports cuCtxCreate_v4; older drivers export the stable v2 interface.
call('cuCtxCreate_v2', c.byref(context), 0, 0)
ptr = c.c_uint64()
module = c.c_void_p()
try:
    call('cuMemAlloc_v2', c.byref(ptr), c.c_size_t(4))
    ptx = b'''.version 7.0
.target sm_50
.address_size 64
.visible .entry write_value(.param .u64 output) {
.reg .b64 %ptr;
.reg .b32 %value;
ld.param.u64 %ptr, [output];
mov.u32 %value, 42;
st.global.u32 [%ptr], %value;
ret;
}
'''
    call('cuModuleLoadData', c.byref(module), c.c_char_p(ptx))
    function = c.c_void_p()
    call('cuModuleGetFunction', c.byref(function), module, b'write_value')
    args = (c.c_void_p * 1)(c.addressof(ptr))
    call('cuLaunchKernel', function, 1, 1, 1, 1, 1, 1, 0, c.c_void_p(), args, c.c_void_p())
    call('cuCtxSynchronize')
    value = c.c_uint32()
    call('cuMemcpyDtoH_v2', c.byref(value), ptr, c.c_size_t(4))
    assert value.value == 42, value.value
    print(json.dumps({'devices': count.value, 'computed': value.value}))
finally:
    if module.value:
        call('cuModuleUnload', module)
    if ptr.value:
        call('cuMemFree_v2', ptr)
    call('cuCtxDestroy_v2', context)
