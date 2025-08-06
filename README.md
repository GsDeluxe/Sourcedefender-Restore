# 🚨 Important Notice 🚨

## ⚠️ Intended Audience Notice ⚠️

This repository is intended for **security researchers** and **developers** who are interested in learning, contributing, and advancing their knowledge in the field of cybersecurity.

If your purpose is to misuse or repurpose this code unethically, Please refrain from using this repository.

---

# 🔐 How Does It Work?

## Sourcedefender: A Tool to Encrypt and Protect Source Code

**Sourcedefender** is a tool designed to **encrypt** and **protect** your source code, ensuring its security and integrity.

In this repository, I will walk you through how **simple it is to reverse engineer** Sourcedefender, along with the methods I used to uncover its vulnerabilities.

# 👀 Discovery & Analysis

## 🪲 x64dbg Analysis

To Run a Sourcedefender protected program you must import Sourcedefender and then the custom `.pye` file, Sourcedefender acts as an import hook and decrypts and executes the code 

```
python -c 'import sourcedefender; test.pye'
```


Now by attaching Python to x64dbg we can get a better insight as to what Sourcedefender uses to decrypt and handle code
Upon import we can view the loaded DLLs 

![](/img/import_sourcedefender.png)

![](/img/loaded_dlls_1.png)

I noticed the inclusion of the `msgpack` and `tgcrypto` libraries, which immediately caught my attention. These third party libraries are being used by **Sourcedefender** to handle encrypted data. This led me to a realization: **If we can modify the code inside these libraries**, will be able to let Sourcedefender to do its decryption dynamically and we can hijack the library and use that to fetch the source code 

So, I started with cloning `msgpack` from [GitHub](https://github.com/msgpack/msgpack-python) and applying these patches to [`_unpacker.pyx`](https://github.com/msgpack/msgpack-python/blob/main/msgpack/_unpacker.pyx)
```python
2a3,4
> import pprint
>
202c204,210
<         return obj
---
>     if isinstance(obj, dict) and 'original_code' in obj:
>         source_code = obj['original_code']
>         print(source_code)
>     else:
>         print("Unpacked data:")
>         pprint.pprint(obj, width=80)
```

Then from there compiled and installed the library.

Now upon loading Sourcedefender again we can see that the loaded DLL is the modified version of `msgpack`

![](/img/loaded_dlls_2.png)

## 📝Manual Analysis

With this, I took an encrypted file from **Sourcedefender** (using the free trial) and ran it through the modified version.

For example, the encrypted file (`test.pye`) looks like this:
```
> type test.pye
---BEGIN PYE FILE---
;d3&~xgiwB!Y7cC2IH~Q
=Sc*6*-$rI9I%_q_lzpH
&fhQkJRV)Q(~-xmmaphB
>Y^NRAY}r1EOy@fTM~I>
ncXh?Dm8(FN9}A`K9Vk*
pTVWO?BEN7MZV4pw|M`I
npjEg;MAl#df0<xB67}D
+kyc~@GM(WNjx2sEVmya
x9a;i
----END PYE FILE----
```

When running the file through the modified version of `msgpack` and attempting to execute it in Python, I observed the following output:
```python
>>> import sourcedefender
>>> import test
source code:
import os
import time
os.system("echo Hello World")

Traceback (most recent call last):
  File "<stdin>", line 1, in <module>
  File "src\\pyx\\loader.pyx", line 546, in loader.MetaLoader.exec_module
ImportError: ImportError: test.pye
>>>
```

As you can see, the source code was successfully dumped out.

At first, I thought I was done, but then a friend sent over a version encrypted with a paid version of **Sourcedefender**. The only difference? It has one more simple layer which was decoding from Python bytecode.

The output from the paid version included a marshalled code object in a Python byte string. 
Here’s an example of the marshalled bytecode output:
```sh
b'c\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x0b\x00\x00\x00@\x00\x00\x00s\xee\x05\x00\x00d\x00d\x01l................................'
```

We can simply convert this marshalled byte string to a code object and then disassemble it back to the source code.

Here’s how you can do it:
```python
import marshal
import dis
import importlib

byte_data = b'c\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x..........'

code_obj = marshal.loads(byte_data)

print(type(code_obj))
dis.dis(code_obj) # human-readable form of the bytecode
print("\nCode object details:")
print(f"File: {code_obj.co_filename}")
print(f"Function name: {code_obj.co_name}")
print(f"Argument count: {code_obj.co_argcount}")
print(f"Constants: {code_obj.co_consts}")
print(f"Variable names: {code_obj.co_names}")

pyc_data = importlib._bootstrap_external._code_to_timestamp_pyc(code_obj) 
with open('bytecode.pyc', 'wb') as f: 
	f.write(pyc_data) # Convert to PYC for disassembly to sourcecode 
```

Now, with this PYC (compiled Python code) file we can use tools like [Decompile++](https://github.com/zrax/pycdc) or [Pylingual](https://github.com/syssec-utd/pylingual) to reconstruct the bytecode back to source code 

I chose to use **Pylingual**, as it uses an AI model to reconstruct the bytecode and is compatible with all Python versions with minimal error. With the the help of this tool, we were able to successfully retrieve the source code from the paid version of **Sourcedefender**.

## 💻 Tool Usage

## Install Dependencies 
```
pip install -r requirements.txt
```

## Run Tool

```
> python restore-sourcecode.py -h
usage: restore-sourcecode.py [-h] file

Sourcedefender Restore

positional arguments:
  file        Path to the .pye file to run

options:
  -h, --help  show this help message and exit
```