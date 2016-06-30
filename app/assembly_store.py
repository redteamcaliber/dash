"""
assembly_store.py: classes and logic for generating and storing the state of
                   the program.

Author: Pete Markowsky <peterm@vodun.org>
"""
import binascii
import cPickle

import capstone
import keystone
#import distorm3

X86 = 'x86'
X64 = 'x64'
ARM = 'arm'
ARM64 = 'arm64'
MIPS = 'mips'

class RowData(object):
  """
  Object representing an individual row of assembly.
  """
  def __init__(self, offset, label, address, opcode, mnemonic, comment, 
               index=0, in_use=False, stack_delta=0):
    self.offset = 0
    self.label = label
    self.address = address
    self.opcode = opcode
    self.mnemonic = mnemonic
    self.comment = comment
    self.index = index
    self.in_use = in_use
    self.error = False
    self.targets = [0]
    self.is_a_data_defintion_inst = False
    self.is_branch_or_call = False
    self.stack_delta = stack_delta

  def ToDict(self):
    return {'offset': self.offset, 
            'label': self.label, 
            'address': self.DisplayAddress(),
            'opcode': self.DisplayOpcode(),
            'mnemonic': self.mnemonic,
            'comment': self.comment,
            'index': self.index,
            'error': self.error,
            'in_use': self.in_use,
            'targets': self.targets,
            'is_a_data_definition_inst': self.is_a_data_defintion_inst,
            'is_a_branch_or_call': self.is_branch_or_call}

  def SetComment(self, comment):
    try:
      self.comment = comment.encode('ascii')
    except Exception:
      pass


  def SetLabel(self, label):
    try:
      self.label = label.encode('ascii').upper()
    except Exception:
      pass

  def SetAddress(self, address):
    try:
      if address.startswith('0x'):
        self.address = int(address, 16) 
      else:
        self.address = int(address)
    except:
      pass

  def DisplayAddress(self):
    return hex(self.address).replace('L', '')

  def SetOpcode(self, hex_str):
    """
    Set the opcodes for the row and make sure that the string is a proper hex string.
    """
    try:
      self.opcode = binascii.unhexlify(hex_str.replace(' ',''))
      self.in_use = True
    except:
      self.in_use = False
      self.opcode = hex_str
      self.mnemonic = '<INVALID OPCODE SUPPLIED>'
      self.error = True

  def SetMnemonic(self, mnemonic):
    """
    Set the mnemonic of the row.

    Args:
      mnemonic: a string

    Returns:
      N / A
    """
    if mnemonic == '':
      self.opcodes = ''
      self.in_use = False
      return

    self.mnemonic = mnemonic

    # this is a hack find a better way to do this
    normalized_mnemonic = mnemonic.lower().strip()
    if normalized_mnemonic.startswith('j') or normalized_mnemonic.startswith('call'):
      self.is_branch_or_call = True
    else:
      self.is_branch_or_call = False

    if normalized_mnemonic.split()[0] in ('db', 'dw', 'dd', 'dq'):
      self.is_a_data_defintion_inst = True
    else:
      self.is_a_data_defintion_inst = False
    # fix capitalization
    if not self.is_a_data_defintion_inst:
      self.mnemonic = self.mnemonic.upper()
    else:
      new_mnemonic = self.mnemonic.split()
      self.mnemonic = ''
      self.mnemonic += new_mnemonic[0].upper() + ' ' + ''.join(new_mnemonic[1:])
    self.in_use = True

  def DisplayOpcode(self):
    """
    Format the opcode string for display
    
    Args:
      N / A
      
    Returns:
      a string of hex bytes separated with spaces
    """
    original_str = binascii.hexlify(self.opcode)
    hex_str = ''

    for i in xrange(len(original_str)):
      hex_str += original_str[i]
      if i % 2 == 1:
        hex_str += ' '

    return hex_str.strip()


class AssemblyStoreError(Exception):
  pass


class AssemblyStore(object):
  """
  This class holds all of the state information for the current assembler session
  """
  _instance = None

  def __new__(cls, *args, **kwargs):
    """
    Override the new operator so as to keept the assembly store a singleton.
    """
    if not cls._instance:
      cls._instance = super(AssemblyStore, cls).__new__(cls, *args, **kwargs)
    return cls._instance

  def __init__(self):
    self.bits = 32
    self.cpu = None
    self.display_labels = True
    self.rows = []
    self.cfg = None
    self.labels = set([])
    self.SetCPU(X86)

    # add 20 empty rows by default.
    for i in xrange(20):
      self.rows.append(RowData(0, '', 0, '' ,'', '', i))
      
  def SetCPU(self, arch):
    arches = {X86: capstone.CS_ARCH_X86,
              X64: capstone.CS_ARCH_X86,
              ARM: capstone.CS_ARCH_ARM,
              ARM64: capstone.CS_ARCH_ARM64,
              MIPS: capstone.CS_ARCH_MIPS}
    
    if arch not in arches:
      raise AssemblyStoreError("Invalid ARCH %s" % arch)
    
    self.cpu = arches[arch]

  def DeepCopyRow(self, index):
    """
    Fast deep copy of a row using cPickle
    """
    if index < 0 or index >= len(self.rows):
      raise AssemblyStoreError("Invalid row index %s" % str(index))

    row = self.rows[index]
    return cPickle.loads(cPickle.dumps(row, -1))

  def ToggleDisplayLabels(self):
    self.display_labels = not self.display_labels

  def SetBits(self, bits):
    """
    Set the operating mode (BITS options in nasm), e.g. 16, 32, or 64

    Args:
      bits: an integer that's either 16,32, or 64

    Returns:
      True if the value was set False otherwise.
    """
    if bits in (16, 32, 64):
      self.bits = bits
      return True
    else:
      return False

  def Reset(self):
    """
    Reset the AssemblyStore's state to an empty AssemblyStore.
    """
    self.cfg = None
    self.rows = []

  def CreateRowFromCapstoneInst(self, index, inst):
    """
    Create rows from a distorm3 instruction instance.

    Args:
      index: a positive integer
      inst: a capstone.CsInsn instance

    Returns:
      N / A
    """
    mnemonic = "%s %s" % (inst.mnemonic, inst.op_str())
    row = RowData(0, '', inst.address, str(inst.bytes), mnemonic, '', 
                  index, in_use=True)
    # check to see if the instruction is a branch instruction else set it's target
    # to address plus length of instructionBytes
    self.InsertRowAt(index, row)

  def InsertRowAt(self, index, row):
    """
    Insert a new row at the index and update the offsets and addresses
    """
    self.rows.insert(index, row)

    for i in xrange(index + 1, len(self.rows)):
      self.rows[i].index = i

    self.UpdateOffsetsAndAddresses()

  def AddTenRows(self):
    """
    Append 10 empty rows
    """
    starting_index = len(self.rows)
    for i in xrange(10):
      self.rows.append(RowData(0, '','','','','', starting_index))
      starting_index += 1

  def ContainsLabel(self, row_asm):
    """
    Check if this row contains a label as a target

    Args:
      row_asm: the string mnemonic of an instruction in a row.

    Returns:
      True if the label is in the target

      False otherwise.
    """
    for label in self.labels:
      if label in row_asm:
        return True

    return False

  def ReplaceLabel(self, row, inst):
    """
    Replace an assembler label.

    Args:
      row: a RowData instance
      inst: a Distorm3 instruction instance

    Returns:
      a string for the new mnemonic of the instruction
    """
    if row.mnemonic.split()[0].lower() != str(inst).split()[0].lower():
      row.error = True
      return ''

    # check the number of [], +, -, *
    for i in ('[', ']', '+', '-', ','):
      if row.mnemonic.count(i) != str(inst).count(i):
        row.error = True
        return ''

    return row.mnemonic.upper()

  def UpdateRow(self, i, new_row):
    """
    Update a row at a given offset
    """
    self.rows[i] = new_row
    if new_row.label != '' and new_row.label not in self.labels:
      self.labels.add(new_row.label)
    # update offsets and addresses
    self.UpdateOffsetsAndAddresses()


  def DeleteRow(self, index):
    self.rows.pop(index)

    # update the row indices
    for i in xrange(0, len(self.rows)):
      self.rows[i].index = i

    self.UpdateOffsetsAndAddresses()


  def UpdateOffsetsAndAddresses(self):
    self.rows[0].offset = 0
    next_address = self.rows[0].address + len(self.rows[0].opcode)
    next_offset = len(self.rows[0].opcode)

    # update offsets and addresses
    for i in xrange(1, len(self.rows)):
      if not self.rows[i].in_use:
        continue

      self.rows[i].address = next_address
      next_address += len(self.rows[i].opcode)
      self.rows[i].offset = next_offset
      next_offset += len(self.rows[i].opcode)

  def ClearErrors(self):
    for i in xrange(len(self.rows)):
      self.rows[i].error = False

  def SetErrorAtIndex(self, index):
    self.rows[index].error = True

  def GetRow(self, i):
    return self.DeepCopyRow(i)

  def GetRows(self):
    """
    Retrieve all of the rows in the store.
    """
    return self.rows

  def GetRowsIterator(self):
    """
    Return an iterator for all of the rows
    """
    for i in xrange(len(self.rows)):
      yield self.DeepCopyRow(i)