import os
from time import sleep
import threading
from functools import partial
import struct
from urllib.parse import urlencode
from urllib.request import urlopen, Request
import json
import hashlib

# After done, only use needed imports
from PySide2.QtUiTools import QUiLoader
from PySide2.QtGui import *
from PySide2.QtWidgets import *
from PySide2.QtCore import *

import blocksec2go
from blocksec2go.comm import observer

import base58
import qrcode

developer = True
reader_name = 'Identiv uTrust 3700 F'
default_wait = 10 # Seconds
# On weaker systems you might want to increase the 
# polling multiplier.
polling_multiplier = 3

## Utility related classes and functions:
class Warning(Exception):
  """ Custom exception to indicate a warning and catch it as an exception.
  
  For more information on exact warning see attached message.
  """
  pass

class SpellingMistake(Exception):
  """ Custom exception to indicate a spelling mistake in the code.
  """
  def __init__(self, message = 'Please check for spelling mistakes in code!'):
    super(Exception, self).__init__(message)

class timer_class:
  """ Wrapper to execute function with a delay.
  """
  def __init__(self):
    self.timer_thread = None

  def start(self, interval, function, *args, **kwargs):
    """ Executes `function` after `interval` seconds.

    Also terminates preexisting delayed functions so that only 1 can 
    be executed at a time.
    """
    self.stop()
    self.timer_thread = threading.Timer(interval, function, args, kwargs)
    self.timer_thread.daemon = True
    self.timer_thread.start()

  def stop(self):
    """ Cancels the execution of a function that has been delayed.
    """
    if(self.timer_thread):
      self.timer_thread.cancel()
      self.timer_thread = None

class log:
  """ Logs the transaction inside a text file.

  This can be used to help you learn how exactly a 
  transaction is build. It also helps you debug 
  a transaction incase it was build incorrectly or 
  doesnt broadcast.
  """
  def __init__(self):
    directory_name = 'transaction logs'
    tx_dir_path = os.path.join(os.path.dirname(__file__), directory_name)
    if not os.path.exists(tx_dir_path):
      os.makedirs(tx_dir_path, exist_ok=True)

    log_index = 1
    tx_file_name = 'transaction_info_' + str(log_index) + '.txt'
    tx_file_path = os.path.join(tx_dir_path, tx_file_name)
    while(os.path.isfile(tx_file_path)):
      log_index = log_index + 1
      tx_file_name = 'transaction_info_' + str(log_index) + '.txt'
      tx_file_path = os.path.join(tx_dir_path, tx_file_name)

    self.log_file = open(tx_file_path,'w+')
    self.write_to_file('Log of Transaction ' + str(log_index) + ':\n')

  def write_to_file(self, log_text = None):
    """ Writes `log_text` into the text file.

    If no `log_text` then it makes a new line.
    """
    if(self.log_file):
      if(log_text):
        self.log_file.write(log_text)
      self.log_file.write('\n')

  def close(self):
    """ Closes the text file.
    """
    if(self.log_file):
      self.log_file.close()
      self.log_file = None

def message(text, mode = None):
  """ Sends `text` to the standard output of the system and
  to the status bar of the application.

  It would be better write `str(text)` here instead of 
  everywhere in the program where the `message` function gets 
  used, but this was not done to debug more easily.
  """
  if((False == developer) and ('dev' == mode)):
    return # No dev messages should be sent if dev mode if off

  if('dev' != mode):
    timer.stop() # Cancel any previous delayed messages

  if((True == developer) and ('dev' == mode)):
    text = 'DEV: ' + text
  elif('warn' == mode):
    text = 'WARNING: ' + text
    ui.status_bar.setStyleSheet('background-color: rgb(245, 198, 49)')
    timer.start(default_wait, message, 'Waiting...')
  elif('error' == mode):
    text = 'ERROR: ' + text
    ui.status_bar.setStyleSheet('background-color: rgb(227, 0, 52)')
    timer.start(default_wait, message, 'Waiting...')
  else:
    text = 'Status: ' + text
    ui.status_bar.setStyleSheet('background-color: rgb(118, 159, 59);')

  print(text)
  if('dev' != mode):
    ui.status_bar.setText(text)

## Card / reader related classes and functions:
class reader_info:
  """ Manages the reader and holds the reader object.
  """
  def __init__(self):
    self.reader = None
    self.card_connected = False

  def get_reader(self):
    """ Identifies reader via a specified name and saves it as 
    its main reader object.
    """
    if(self.reader == None):
      try:
        self.reader = blocksec2go.find_reader(reader_name)
        message('Found the specified reader and a card!')
        return self.reader
      except Exception as details:
        if(str(details) == 'No reader found'):
          message('No card reader found!     \r', 'dev')
          return None 
        elif(str(details) == 'No card on reader'):
          message('Found reader, but no card!\r', 'dev')
          return None 
        else:
          message(str(details), 'error')
          return None 
    else:
      return self.reader

def activate_card():
  """ Enables communication to the Blockchain Security 2Go card.
  
  Also ensures that all other cards are rejected.
  """
  try:
    blocksec2go.select_app(reader.reader)
    message('Found / reset Blockchain Security 2Go card!', 'dev')
    return True
  except Exception as details:
    message(str(details), 'error')
    return False

def generate_keypair():
  """ Generates a new keypair on the Blockchain Security 2Go card.
  
  Keep in mind that you can not specify the keypair slot.
  This is managed by the card itself.
  """
  try:
    key_id = blocksec2go.generate_keypair(reader.reader)
    if(valid_key(key_id)):
      message('Generated a new keypair at slot ' + str(key_id))
      key_button = ui.window.findChild(QPushButton, 'key_' + str(key_id))
      key_button.setStyleSheet('border: 1px solid;')
      key_button.setEnabled(True)
    else:
      raise RuntimeError('Generated keypair has become obsolete!')
  except Exception as details:
    message(str(details), 'error')

def get_keypair_info(key_id):
  """ Gets keypair information from the Blockchain Security 2Go card.
  
  This may either be the counters specifying how many times you can 
  generate a signature or the public key on a specified keypair.
  """
  try:
    return blocksec2go.get_key_info(reader.reader, key_id)
  except Exception as details:
    message(str(details), 'error')

def valid_key(key_id):
  """ Checks the specified keypair for its existence and validity.
  """
  try:
    return blocksec2go.is_key_valid(reader.reader, key_id)
  except Exception as details:
    message(str(details), 'error')

def verify_pin():
  """ Verifies a PIN value on the Blockchain Security 2Go card.
  """
  try:
    status = blocksec2go.verify_pin(reader.reader, ui.pin.text())
    if((True == status) and (isinstance(status, bool))):
      message('OK - Verified!')
      ui.select_pin_button.setStyleSheet('background-color: rgb(118, 159, 59);border: none;')
      ui.select_pin_button.setCursor(Qt.ForbiddenCursor)
    elif(0 != status):
      message(str(status) + ' tries left!', 'error')
      ui.select_pin_button.setStyleSheet('background-color: rgb(227, 0, 52);border: none;')
      ui.select_pin_button.setCursor(Qt.ArrowCursor)
    else:
      message('PIN locked!', 'error')
      ui.select_pin_button.setStyleSheet('background-color: rgb(227, 0, 52);border: none;')
      ui.select_pin_button.setCursor(Qt.ForbiddenCursor)
      ui.select_pin_button.setEnabled(False)
  except Exception as details:
    message(str(details), 'error')

def generate_signature(key_id, hashed_tx):
  """ Generates a signature with keypair `key_id` using `hashed_tx`.

  The returned signature is in the DER encoded format.
  No exception catching on purpose!
  """
  return blocksec2go.generate_signature(reader.reader, int(key_id), hashed_tx)

def card_connect(self):
  """ Callback for when the Blockchain Security 2Go card is inserted.
  
  This triggeres always when any card is connected to any reader!
  """
  if(not reader.reader): 
    if(None == reader.get_reader()):
      message('Please check reader and card!', 'warn')
    else:
      # Do not combine 2 if statements because 2nd statement always resets PIN.
      if(not reader.card_connected): # 1st if: Actually checks if card is connected.
        if(activate_card()): # 2nd if: Makes sure connected card is Blockchain Security 2Go card.
          try:
            app.setOverrideCursor(Qt.WaitCursor)
            ui.verify_key_buttons()
            reader.card_connected = True
            message('Card connected!')
            ui.switch_to_frame('keypair')
          except Exception as details:
            message(str(details), 'error')
          finally:
            app.changeOverrideCursor(Qt.ArrowCursor)
            threading.Timer(0.5, app.restoreOverrideCursor).start() # Reset Cursor

def card_disconnect(self):
  """ Callback for when the Blockchain Security 2Go card is removed.
  
  This triggeres always when any card is removed from any reader!
  """
  if((reader.reader)):
    if(activate_card()):
      message('Another card was removed! Please reconfirm your PIN!', 'warn')
      ui.card.reset_pin()
    else:
      reader.card_connected = False
      message('Card removed!')
      reader.reader = None
      ui.switch_to_frame('no_card')
      ui.flush_key_buttons()
      ui.clear_card_frame()

## UI related classes and functions:
class UI:
  """ Manages application UI and its elements.
  """
  def __init__(self, window):
    self.window = window
    self.window.setWindowFlags(Qt.FramelessWindowHint)
    self.keypairs = keys(self)
    self.card = card(self)
    self.confirm = confirmation(self)

    self.blockchain_poll = None

    self.init_ui_elements()
    self.keypairs.generate_buttons()

  @classmethod
  def load(ui_cls):
    """ Loads the application UI via a fixed path.
    """
    ui_file_loc = os.path.join(os.path.dirname(__file__), 'mainwindow.ui')
    ui_file = QFile(ui_file_loc)
    ui_file.open(QFile.ReadOnly)

    loader = QUiLoader()
    window = loader.load(ui_file)
    ui_file.close()
    return ui_cls(window)

  def show_window(self):
    """ Shows window widget.
    """
    self.window.show()
    self.no_card_frame.show()
    message('Welcome!')

  def init_ui_elements(self):
    """ Finds and configures most UI elements.
    """
    # Set main widget
    self.widget = self.window.findChild(QWidget, 'main_widget')

    # Set exit button
    self.exit_button = self.window.findChild(QPushButton, 'exit_button')
    self.exit_button.clicked.connect(self.window.close)

    # Set status bar
    self.status_bar = self.window.findChild(QLabel, 'status_bar_text')

    # Set and hide all main frames
    self.no_card_frame = self.window.findChild(QFrame, 'no_card')
    self.keys_frame = self.window.findChild(QFrame, 'key')
    self.card_frame = self.window.findChild(QFrame, 'card')
    self.confirmation_frame = self.window.findChild(QFrame, 'confirmation')
    self.hide_mainframes()

    # Set keypair_frame
    self.keys_grid = self.window.findChild(QGridLayout, 'key_grid_layout')

    self.generate_key_button = self.window.findChild(QPushButton, 'generate_key')
    self.generate_key_button.clicked.connect(generate_keypair)

    self.key_id = self.window.findChild(QLineEdit, 'key_id')
    self.key_id.setValidator(QIntValidator(1, self.keypairs.get_key_id_max()))

    self.select_key_button = self.window.findChild(QPushButton, 'select_key')
    self.select_key_button.clicked.connect(self.select_keypair)

    # Set card_frame
    self.target_address = self.window.findChild(QLineEdit, 'tar_addr')
    self.amount = self.window.findChild(QLineEdit, 'amount')
    self.amount.textChanged.connect(self.update_poll)
    self.amount.setValidator(QIntValidator())
    self.amount_converter = self.window.findChild(QLabel, 'amount_result')
    self.fee = self.window.findChild(QLineEdit, 'fee')
    self.fee.textChanged.connect(self.update_poll)
    self.fee.setValidator(QIntValidator())
    self.fee_converter = self.window.findChild(QLabel, 'fee_result')
    self.card.set_default_amount_and_fee()

    self.qrcode_holder = self.window.findChild(QLabel, 'qrcode_image')
    self.qrcode_description = self.window.findChild(QLabel, 'btc_addr')
    self.global_counter_info = self.window.findChild(QLabel, 'global_counter')
    self.counter_info = self.window.findChild(QLabel, 'counter_text')
    self.key_id_info = self.window.findChild(QLabel, 'key_id_text')

    self.balance = self.window.findChild(QLabel, 'my_balance')
    self.pin = self.window.findChild(QLineEdit, 'pin_line_edit')

    self.select_keypair_button = self.window.findChild(QPushButton, 'select_keypair')
    self.select_keypair_button.clicked.connect(partial(self.switch_to_frame, 'keypair'))

    self.generate_transaction_button = self.window.findChild(QPushButton, 'generate_transaction')
    self.generate_transaction_button.clicked.connect(self.card.generate_transaction)

    self.select_pin_button = self.window.findChild(QPushButton, 'select_pin')
    self.select_pin_button.clicked.connect(verify_pin)

    # Set confirmation_frame
    self.confirm_layout = self.window.findChild(QVBoxLayout, 'confirm_layout')
    self.confirm_button = self.window.findChild(QPushButton, 'confirm')
    self.deny_button = self.window.findChild(QPushButton, 'deny')
    self.confirm.init_frame()

  def hide_mainframes(self):
    """ Hides all the window frames.

    Used to clear the window so that a new frame can be opened 
    properly.
    """
    self.no_card_frame.hide()
    self.keys_frame.hide()
    self.card_frame.hide() 
    self.confirmation_frame.hide()

  def switch_to_frame(self, frame):
    """ Switches to `frame` window. 
    """
    poll.stop()
    self.hide_mainframes()
    if('no_card' == frame):
      self.no_card_frame.show()
      message('Welcome!')
    elif('keypair' == frame):
      self.keys_frame.show()
      message('Please select a keypair!')
    elif('card' == frame):
      self.card_frame.show()
      message('Ready to use!')
    elif('confirm' == frame):
      self.confirmation_frame.show()
    else:
      raise SpellingMistake()

    timer.start(default_wait, message, 'Waiting...')

  def verify_key_buttons(self):
    """ Verifies all keypairs and updates the key buttons accordingly.
    """
    self.keypairs.verify(self.window)
  
  def flush_key_buttons(self):
    """ Flushes all keypair buttons to avoid graphical errors.
    """
    self.keypairs.flush(self.window)

  def select_keypair(self):
    """ Checks and selects the specified keypair.

    This keypair is used for any further actions, such as 
    creating the BTC address or signing a transaction.
    """
    key_id = self.key_id.text()
    if(('' != key_id) and (1 <= int(key_id) <= self.keypairs.get_key_id_max()) and (valid_key(int(key_id)))):
      message('Keypair ' + key_id + ' selected!')
      key_id = int(key_id)
      global_counter, counter, key = get_keypair_info(key_id)
      btc_addr = pub_key_to_BTC_Addr(key)
      self.card.create_qrcode(btc_addr)
      self.card.set_key_info(key_id, global_counter, counter)
      self.card.set_pub_key(key)
      threading.Thread(target = self.start_poll, args = [btc_addr]).start()
      self.switch_to_frame('card')
    else:
      message('Please select a valid keypair!', 'warn')
      timer.start(default_wait, message, 'Waiting...')

  def clear_card_frame(self):
    """ Clears / resets the card_frame. 
    """
    self.card.reset()

  def start_poll(self, btc_addr):
    self.balance.setText('Please wait!')
    self.amount_converter.setText((' ') * 45)
    self.fee_converter.setText((' ') * 45)
    try:
      self.blockchain_poll = blockchain_info_poll(btc_addr)
    except Warning as details:
      message(str(details), 'warn')
    except Exception as details:
      message(str(details), 'error')

  def update_poll(self):
    self.blockchain_poll.update_currency_rate()

class keys:
  """ Manages buttons on the keypair frame.
  """
  def __init__(self, ui):
    self.ui = ui
    self._row_max = 11
    self._column_max = 26
    self.__key_id_max = 0xFD

  @staticmethod
  def paint_button(window, key_id, key_list = None):
    """ Paints the keypair UI buttons depending on 
    their validity .
    """
    key_button = window.findChild(QPushButton, 'key_' + str(key_id + 1))
    if(key_list):
      if(key_list[key_id]):
        key_button.setStyleSheet('border: 1px solid;')
        key_button.setEnabled(True)
      else:
        key_button.setStyleSheet('background-color: rgb(146, 130, 133); border: none;')
        key_button.setEnabled(False)
    else:
      key_button.setStyleSheet('background-color: rgb(146, 130, 133); border: none;')
      key_button.setEnabled(False)

  def get_key_id_max(self):
    """ Returns the maximum number of keypair slots on the 
    Blockchain Security 2Go card.
    """
    return self.__key_id_max

  def generate_buttons(self):
    """ Generates `__key_id_max` buttons in the keypair frame.
    
    The structural layout of the buttons can be changed 
    easily by adjusting `_row_max` and `_column_max`.

    All of the values are found in the initializer method.
    """
    for row in range(0, self._row_max):
      for column in range(0, self._column_max):
        key_id = self._column_max * row + column + 1
        if(self.__key_id_max >= key_id):
          key_button = QPushButton('Key_' + str(key_id))
          key_button.setObjectName('key_' + str(key_id))
          key_button.setText(str(key_id))
          key_button.clicked.connect(partial(self.ui.key_id.setText, str(key_id)))
          key_button.setMinimumSize(QSize(28, 28))
          key_button.setMaximumSize(QSize(28, 28))
          key_button.setStyleSheet('background-color: rgb(146, 130, 133); border: none;')
          key_button.setFont(QFont('Source Sans Pro', 11))
          key_button.setEnabled(False)
          self.ui.keys_grid.addWidget(key_button, row, column)

  def verify(self, window):
    """ Verifies all keypairs and updates the key buttons accordingly.
    """
    message('Verifying all keypairs!', 'warn')
    key_list = [None] * self.__key_id_max
    for key_id in range(0, self.__key_id_max):
      validity = valid_key(key_id + 1)
      if(validity):
        key_list[key_id] = True
      elif(False == validity):
        key_list[key_id] = False
      else:
        raise RuntimeError('Please reinsert card into card reader!')
      message('Verified key ' + str(key_id + 1), 'dev')
  
    for key_id in range(0, self.__key_id_max):
      threading.Thread(target = self.paint_button, args = (window, key_id, key_list)).start()
    message('Done verifying all keypairs!', 'warn')
    window.update()

  def flush(self, window):
    """ Flushes all keypair buttons to avoid graphical errors.
    """
    self.ui.key_id.setText('')
    for key_id in range(0, self.__key_id_max):
      threading.Thread(target = self.paint_button, args = (window, key_id)).start()
    window.update()

class card:
  """ Manages buttons and text fields in the card frame.
  """
  def __init__(self, ui):
    self.ui = ui
    img_name = 'BTC_Address.png'
    self.img_path = os.path.join(os.path.dirname(__file__), img_name)
    
    self.default_amount = None
    self.default_fee = None
    self.__pub_key = None
    self.blockchain = None
    self.logger = None

  def set_default_amount_and_fee(self):
    """ Saves init amount and fee so that they can be 
    reset when the card is removed from the reader.
    """
    self.default_amount = self.ui.amount.text()
    self.default_fee = self.ui.fee.text()

  def set_pub_key(self, public_key):
    """ Sets the public key which is used to build 
    a transaction.
    """
    self.__pub_key = public_key

  def set_key_info(self, key_id, global_counter, counter):
    """ Sets information about the selected keypair on 
    the card frame.
    """
    self.ui.key_id_info.setText(str(key_id))
    self.ui.global_counter_info.setText(str(global_counter))
    self.ui.counter_info.setText(str(counter))

  def create_qrcode(self, btc_addr):
    """ Creates qrcode by using a bitcoin address.

    The qrcode is also saved as an image as long as the 
    card is connected and a key is selected.
    """
    qrcode_img = qrcode.make(btc_addr)
    qrcode_img.save(self.img_path)
    self.ui.qrcode_holder.setObjectName('qrcode')
    self.ui.qrcode_holder.setPixmap(QPixmap(self.img_path).scaledToWidth(300))
    self.ui.qrcode_description.setText(btc_addr)
    message('Created qrcode!', 'dev')

  def remove_qrcode(self):
    """ Removes qrcode elements and deletes image from 
    the system. 
    """
    self.ui.qrcode_holder.clear()
    self.ui.qrcode_description.clear()
    if(os.path.exists(self.img_path)):
      os.remove(self.img_path)
      message('Removed qrcode!', 'dev')

  def generate_transaction(self):
    """ Generates a transaction that is ready to be 
    broadcasted.
    """
    btc_addr = self.ui.qrcode_description.text()
    try:
      message('Generating transaction!')
      ui.switch_to_frame('confirm')
      self.logger = log()
      tx = transaction(btc_addr, self.logger)
      signed_tx = tx.make(self.__pub_key)
      message('Broadcastable Transaction:', 'dev')
      message(signed_tx.hex(), 'dev')
      ui.confirm.set_transaction(signed_tx)
      ui.confirm.transaction_done()
    except Warning as details:
      ui.switch_to_frame('card')
      message(str(details), 'warn')
      self.logger.write_to_file('Warning occured: ' + str(details))
      self.logger.close()
    except Exception as details:
      ui.switch_to_frame('card')
      message(str(details), 'error')
      self.logger.write_to_file('Error occured: ' + str(details))
      self.logger.close()

  def reset_pin(self):
    """ Resets the PIN field and the PIN button.
    
    Since the PIN unlocks the card it should only be reset 
    if the card gets changed.
    """
    self.ui.pin.clear()
    self.ui.select_pin_button.setStyleSheet('background-color: rgb(146, 130, 133);border: none;')
    self.ui.select_pin_button.setCursor(Qt.ArrowCursor)
    self.ui.select_pin_button.setEnabled(True)

  def reset(self):
    """ Clears / resets the card_frame. 
    """
    self.remove_qrcode()
    self.reset_pin()
    self.ui.amount.setText(self.default_amount)
    self.ui.fee.setText(self.default_fee)

class confirmation:
  """ Manages buttons and text fields in the confirmation frame.
  """
  def __init__(self, ui):
    self.ui = ui

    self.broadcastable_tx = None
    self.payment_info = None
    self.info_label = None
    self.transaction_browser = None
    self.btc_addr = None

  def init_frame(self):
    """ Sets the buttons and hides them since they will 
    not be needed until later.
    """
    self.info_label = QLabel()
    self.transaction_browser = QTextBrowser()
    self.ui.confirm_layout.addWidget(self.info_label)
    self.ui.confirm_layout.addWidget(self.transaction_browser)
    self.ui.confirm_button.clicked.connect(self.broadcast_tx)
    self.ui.deny_button.clicked.connect(partial(self.ui.switch_to_frame, 'card'))
    self.ui.confirm_button.hide()
    self.ui.deny_button.hide()

  def set_transaction(self, transaction):
    """ Sets the broadcastable transaction which will be pushed to the mempool.
    """
    self.broadcastable_tx = transaction

  def set_payment_info(self, amount, fee, change):
    """ Sets the payment info that is shown in the confirmation frame.
    """
    self.payment_info = (str(amount), str(fee), str(change))

  def show_information(self):
    """ Shows information about the transaction.
    """
    self.btc_addr = self.ui.qrcode_description.text()
    target_addr = self.ui.target_address.text()

    address = (
        'Own Address: '
      + self.btc_addr
      + '\n'
      + 'Target Address: '
      + target_addr
      )
    payment_info = (
      'Amount: '
      + self.payment_info[0]
      + '\n'
      + 'Fee: '
      + self.payment_info[1]
      + '\n'
      + 'Returned change: '
      + self.payment_info[2]
    )
    broadcastable_tx = ('Signed Transaction:')

    info_label_str = address + '\n\n' + payment_info + '\n\n' + broadcastable_tx
    self.info_label.setText(info_label_str)
    self.info_label.setFont(QFont('Source Sans Pro', 14))
    self.info_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    self.transaction_browser.setText(self.broadcastable_tx.hex())
    self.transaction_browser.setFont(QFont('Source Sans Pro', 10))
    self.transaction_browser.setStyleSheet('border: 1px solid;')

  def transaction_done(self):
    """ Shows confirmation buttons after the transaction is generated!
    """
    self.ui.confirm_button.show()
    self.ui.deny_button.show()
    message('Generated a new transaction successfully!')
    timer.start(default_wait, message, 'Please ensure the correctness of the data above before broadcasting!')

    self.show_information()

  def broadcast_tx(self):
    """ Broadcasts a signed transaction into the mempool.
    """
    try:
      ui.switch_to_frame('card')
      push_url = 'https://blockchain.info/pushtx'
      if(self.broadcastable_tx):
        transaction = {'tx' : self.broadcastable_tx.hex()}
        data = urlencode(transaction).encode()
        req =  Request(push_url, data = data)
        urlopen(req)

        # Also update balance in card window
        if(self.btc_addr):
          ui.blockchain_poll.update_currency_rate(self.btc_addr)
      else:
        raise Warning('No broadcastable transaction!')
    except Warning as details:
      message(str(details), 'warn')
    except Exception as details:
      message(str(details), 'error')

def close_event():
  """ Cleans up and exits program.
  """
  ui.clear_card_frame() # Delete qrcode image
  if(ui.card.logger):
    ui.card.logger.close()
  observer.stop(cardmonitor, cardobserver)
  if(reader.card_connected == True):
    activate_card() # Reset PIN
  message('Exit!')
  exit()

## Bitcoin related classes and functions:
def pub_key_to_BTC_Addr(public_key):
  """ Transforms a raw `public_key` into a base58 encoded 
  Bitcoin adress.
  """
  # Public Key
  message('public_key:', 'dev')
  message(public_key.hex(), 'dev')

  # Ripemd160(Sha256(Public Key))
  message('Ripemd160(Sha256(public_key)):', 'dev')
  # SHA256
  hash = hashlib.sha256()
  hash.update(public_key)
  hash_result = hash.digest()
  # RIPEMD160
  hash = hashlib.new('ripemd160')
  hash.update(hash_result)
  hash_result = hash.digest()
  message(hash_result.hex(), 'dev')

  # Add Bitcoin Network ID
  # --> Main Network: 0x00 <--
  #     Test Network: 0x6F
  message('Add Main Bitcoin Network ID:', 'dev')
  network_byte = bytes([0x00])
  result = network_byte + hash_result
  message(result.hex(), 'dev')

  # Checksum (2 x SHA256)
  message('Get Checksum:', 'dev')
  # SHA256
  # First Hash
  hash = hashlib.sha256()
  hash.update(result)
  hash_result = hash.digest()
  # Second Hash
  hash = hashlib.sha256()
  hash.update(hash_result)
  checksum_result = hash.digest()
  message(checksum_result.hex(), 'dev')
  message('Get first 4 Checksum bytes:', 'dev')
  message(checksum_result[:4].hex(), 'dev')

  # Add Checksum
  message('Add Checksum:', 'dev')
  result = result + checksum_result[:4]
  message(result.hex(), 'dev')

  # Base58
  message('Bitcoin Address:', 'dev')
  btc_addr = base58.b58encode(result).decode('utf-8')
  message(btc_addr, 'dev')
  return btc_addr

class transaction:
  """ Manages the Bitcoin transaction structure and 
  generates a broadcastable transaction.
  """
  def __init__(self, btc_addr, logger):
    self.btc_addr = btc_addr
    self.blockchain = blockchain_info(self.btc_addr)
    self.logger = logger
    self.tx_helper = transaction_helper(self.blockchain, self.logger)

  def make(self, public_key):
    """ Builds unsigned and signed transactions.

    Keep in mind that the number of signatures generated depends on 
    how many inputs you have, not how many transaction you do!
    """
    Version = self.tx_helper.get_version()
    Number_of_TxIn = self.blockchain.get_total_input_number()
    if(Number_of_TxIn >= 0xFD):
      raise Warning('Too many Inputs - transaction fees might be too high!')

    SigScript = [None] * Number_of_TxIn
    old_PkScript = self.tx_helper.get_pub_key_script(self.btc_addr)
    
    Standard_TxOut = self.tx_helper.make_tx_outputs()
    Number_of_TxOut = self.tx_helper.get_total_output_number()

    self.logger.write_to_file('Own address: ' + ui.qrcode_description.text())
    self.logger.write_to_file('Target address: ' + ui.target_address.text())
    self.logger.write_to_file()
    self.logger.write_to_file('Amount: ' + ui.confirm.payment_info[0])
    self.logger.write_to_file('Fee: ' + ui.confirm.payment_info[1])
    self.logger.write_to_file('Change: ' + ui.confirm.payment_info[2])
    self.logger.write_to_file('\n')

    LockTime = self.tx_helper.get_lock_time()
    HashTypeCode = self.tx_helper.get_hash_type_code('SIGHASH_ALL')

    for script in range(Number_of_TxIn):
      self.logger.write_to_file('  Unsigned transaction for input ' + str(script + 1) + ':')
      self.logger.write_to_file('    Version: ' + Version.hex())
      self.logger.write_to_file('    Number of transaction inputs: ' + bytes([Number_of_TxIn]).hex())
      
      All_Standard_TxIn = bytes()

      Standard_TxIn = [None] * Number_of_TxIn
      Standard_TxIn[script] = old_PkScript

      for TxIn in range(Number_of_TxIn):
        All_Standard_TxIn = All_Standard_TxIn + self.tx_helper.make_tx_input('unsigned', TxIn, Standard_TxIn)

      self.logger.write_to_file('    Number of transaction outputs: ' + Number_of_TxOut.hex())
      self.logger.write_to_file('    Standard TxOut: ' + Standard_TxOut.hex())

      tx_to_sign = (
          Version
        + bytes([Number_of_TxIn])
        + All_Standard_TxIn
        + Number_of_TxOut
        + Standard_TxOut
        + LockTime
        + HashTypeCode
      )

      key_id = ui.key_id_info.text()
      hashed_tx_to_sign = hashlib.sha256(hashlib.sha256(tx_to_sign).digest()).digest()
      global_counter, counter, signature = generate_signature(key_id, hashed_tx_to_sign)

      ui.card.set_key_info(key_id, global_counter, counter)

      constant = self.tx_helper.get_op_code('N/A', 0x01)
      signature_len = bytes([len(signature) + len(constant)])
      public_key_len = bytes([len(public_key)])

      self.logger.write_to_file('  Transaction to sign prehash: ' + tx_to_sign.hex())
      self.logger.write_to_file('  Transaction to sign hash: ' + hashed_tx_to_sign.hex())
      self.logger.write_to_file('  Signature for standard transaction input ' + str(script + 1) + ': ' + signature.hex())
      self.logger.write_to_file()
      
      SigScript[script] =  signature_len + signature + constant + public_key_len + public_key

    self.logger.write_to_file()
    self.logger.write_to_file('  Public key: ' + public_key.hex())

    All_Standard_TxIn = bytes()
    for TxIn in range(Number_of_TxIn):
      All_Standard_TxIn = All_Standard_TxIn + self.tx_helper.make_tx_input('signed', TxIn, SigScript)

    signed_tx = (
          Version
        + bytes([Number_of_TxIn])
        + All_Standard_TxIn
        + Number_of_TxOut
        + Standard_TxOut
        + LockTime
      )

    self.logger.write_to_file('  Signed Transaction: ' + signed_tx.hex())
    
    self.logger.close()

    return signed_tx

class transaction_helper:
  def __init__(self, blockchain, logger):
    self.logger = logger
    self.blockchain = blockchain
    self.change_present = None

  def get_version(self):
    """ The `version` shows the format and version of the 
    Bitcoin transaction.

    This is almost always 1. Keep in mind that this version 
    number has a different meaning than the block version 
    number.
    """
    version = 0x00000001
    return struct.pack('<L', version)

  def make_tx_input(self, transaction_type, cycle, script):
    """ Builds a single standard transaction input based on `type`.
    
    Variable names are different to be exact 1-to-1 copies of the 
    variable names used in the bitcoin wiki.
    """
    TxOutHash = bytes.fromhex(self.blockchain.get_tx_hash(cycle))
    TxOutIndex = struct.pack('<L', self.blockchain.get_tx_o_n(cycle))

    # The sequence changes depending on the lock time
    Sequence = struct.pack('<L', 0xFFFFFFFF)

    if('unsigned' == transaction_type):
      if(None == script[cycle]):
        ScriptLen = bytes([0x00])
        SigScript = bytes()
      elif(bytes == type(script[cycle])):
        ScriptLen = len(script[cycle])
        if(0x00 < ScriptLen < 0xFD):
          ScriptLen = struct.pack('<B', ScriptLen)
        elif(0xFD <= ScriptLen <= 0xFFFF):
          ScriptLen = struct.pack('<H', ScriptLen)
          message('Script unusually long!', 'warn')
        elif(0xFFFF < ScriptLen <= 0xFFFFFFFF):
          ScriptLen = struct.pack('<L', ScriptLen)
          message('Script unusually long!', 'warn')
        elif(0xFFFFFFFF < ScriptLen < 0xFFFFFFFFFFFFFFFF):
          ScriptLen = struct.pack('<Q', ScriptLen)
          message('Script unusually long!', 'warn')
        else:
          raise Warning('SigScript too long!') 
        SigScript = script[cycle]
      else:
        raise RuntimeError('Unsigned transaction - SigScript invalid!')
    elif('signed' == transaction_type):
      ScriptLen = len(script[cycle])
      if(0x00 < ScriptLen < 0xFD):
        ScriptLen = struct.pack('<B', ScriptLen)
      elif(0xFD <= ScriptLen <= 0xFFFF):
        ScriptLen = struct.pack('<H', ScriptLen)
      elif(0xFFFF < ScriptLen <= 0xFFFFFFFF):
        ScriptLen = struct.pack('<L', ScriptLen)
        message('Script unusually long!', 'warn')
      elif(0xFFFFFFFF < ScriptLen < 0xFFFFFFFFFFFFFFFF):
        ScriptLen = struct.pack('<Q', ScriptLen)
        message('Script unusually long!', 'warn')
      else:
        raise Warning('SigScript too long!')
      SigScript = script[cycle]
    else:
      raise SpellingMistake()

    self.logger.write_to_file('    Standard TxIn ' + str(cycle + 1) + ':')
    self.logger.write_to_file('      TxOutHash: ' + TxOutHash.hex())
    self.logger.write_to_file('      TxOutIndex: ' + TxOutIndex.hex())
    self.logger.write_to_file('      ScriptLen: ' + ScriptLen.hex())
    self.logger.write_to_file('      SigScript: ' + SigScript.hex())
    self.logger.write_to_file('      Sequence: ' + Sequence.hex())

    Standard_TxIn = TxOutHash + TxOutIndex + ScriptLen + SigScript + Sequence
    return Standard_TxIn

  def get_pub_key_script(self, btc_addr):
    """ Decodes and strips the Bitcoin address to the format that 
    is achived when you hash the public key - `RIPEMD160(SHA256(public_key))`.
    """
    btc_addr_striped = base58.b58decode(btc_addr)[1:21]
    pub_key_script = (
        self.get_op_code('OP_DUP')
      + self.get_op_code('OP_HASH160')
      + bytes([0x14])
      + btc_addr_striped
      + self.get_op_code('OP_EQUALVERIFY')
      + self.get_op_code('OP_CHECKSIG')
      )
    return pub_key_script

  def get_total_output_number(self):
    """ Describes how many outputs exist.

    If there is no change left after the transaction is done, then there 
    is 1 output (to the target address), else there are 2 outputs. One to 
    the target and one to the sender her-/himself.
    """
    if(self.change_present == False):
      output_number = 0x01
    else:
      output_number = 0x02
    return bytes([output_number])

  def make_tx_outputs(self):
    """ Calculates the returned change, if any exists and builds all 
    standard outputs.

    The fees of a transaction are all the Satoshi that are not used by 
    the outputs of the transaction. 
    This is why its crucial to calculate the change. 
    Another very important thing about this part of the transaction is 
    the fact that values under the so called `dust` value should not be 
    broadcasted.
    """
    amount = int(ui.amount.text())
    fee = int(ui.fee.text())

    total_bal = 0
    min_tx_amount = 546 # minimum amount of satoshi required for tx

    total_bal = self.blockchain.get_bal_of_uo()
    change = total_bal - (amount + fee)

    # message('Total Balance: ' + str(total_bal), 'dev')
    # message('Target amount: ' + str(amount), 'dev')
    # message('Fee: ' + str(fee), 'dev')
    # message('Change: ' + str(change), 'dev')

    ui.confirm.set_payment_info(amount, fee, change)

    if(total_bal < amount + fee):
      raise Warning('Balance too low for this transaction!')
    elif(0 < change < min_tx_amount):
      adjust_for_dust = change
      ui.fee.setText(str(fee + adjust_for_dust))
      raise Warning('Change falls under Dust value! Fees have been adjusted!')
    else:
      all_outputs = bytes()

      value = struct.pack('<Q', int(amount))
      script_len = bytes([0x19]) # Standard PkScript len = 25 Bytes
      recipient_addr = self.get_pub_key_script(ui.target_address.text())

      output_target = (
          value
        + script_len
        + recipient_addr
        )

      if(0 == change):
        self.change_present = False
        output_self = bytes()
      else:
        self.change_present = True

        value = struct.pack('<Q', int(change))
        script_len = bytes([0x19]) # Standard PkScript len = 25 Bytes
        recipient_addr = self.get_pub_key_script(ui.qrcode_description.text())

        output_self = (
            value
          + script_len
          + recipient_addr
          )

      all_outputs = output_target + output_self
      return all_outputs

  def get_op_code(self, code, constant = None):
    """ The opcodes are script words or commands that are understood 
    by the Bitcoin protocol and execute a certain function or stand 
    as a variable.

    `N/A`: Pushes the next `constant` bytes as data onto the stack

    `OP_DUP`: Duplicates the item on the top of the stack.

    `OP_EUALVERIFY`: Checks if the top 2 items on the stack are equal 
    to each other.

    `OP_HASH160`: Hashes the item on the top of the stack. First SHA256 
    then RIPEMD160.

    `OP_CHECKSIG`: Checks the signature on the top 2 stack items.

    For more information on these, please check the Bitcoin Wiki pages 
    about the transaction and the script.
    """
    if(('N/A' == code) and (constant)):
      code_value = constant
    elif('OP_DUP' == code):
      code_value = 0x76
    elif('OP_EQUALVERIFY' == code):
      code_value = 0x88
    elif('OP_HASH160' == code):
      code_value = 0xa9
    elif('OP_CHECKSIG' == code):
      code_value = 0xac
    else:
      raise SpellingMistake()
    return bytes([code_value])

  def get_lock_time(self):
    """ The `lock_time` delays the transaction by either a 
    set amount of time or till a certain block height is 
    reached.
    
    After that time has been surpassed or the block 
    height has been reached the transaction is eligible 
    to be mined into a block. 
    This means that after the lock time is over the 
    speed of the transaction still depends on the 
    transaction fee.
    """
    lock_time = 0x00000000
    return struct.pack('<L', lock_time)

  def get_hash_type_code(self, code):
    """ The hash code describes what parts of the 
    transaction should be signed.

    If you really want to know what exactly this does I
    highly recommend reading this wiki page: 
    https://en.bitcoin.it/wiki/OP_CHECKSIG
    """
    if('SIGHASH_ALL' == code):
      code_value = 0x00000001
    elif('SIGHASH_NONE' == code):
      code_value = 0x00000002
    elif('SIGHASH_SINGLE' == code):
      code_value = 0x00000003
    elif('SIGHASH_ANYONECANPAY' == code):
      code_value = 0x00000080
    else:
      raise SpellingMistake()
    return struct.pack('<L', code_value)

class blockchain_info:
  """ Manages information from the website Blockchain.info.
  
  This is done to recieve the unspent outputs of a 
  Bitcoin address or the current exchange rate of Bitcoin.
  """
  def __init__(self, btc_addr):
    confirmed = 0 # This should be set to 6 if you want to make sure that the previous transaction is definitly valid. 
    max_inputs = 50
    restrictions = '&confirmations=' + str(confirmed) + '&limit=' + str(max_inputs)
    url = 'https://blockchain.info/unspent?active=' + btc_addr + restrictions
    try:
      unspent_outputs_data = json.loads(urlopen(url, timeout = default_wait).read())
    except Exception as details:
      raise Warning('No valid btc address or no unspent outputs!')
    self._data = unspent_outputs_data['unspent_outputs']

  def get_total_input_number(self):
    """ Describes how many unspent outputs i.e. inputs exist.
    """
    return len(self._data)

  def get_bal_of_uo(self):
    """ Calculates the total value of the unspent outputs.
    """
    balance = 0
    for unspent_output in self._data:
      balance = balance + unspent_output['value']
    return balance

  def get_tx_hash(self, output_number):
    """ Returns the transaction hash of an unspent output.
    """
    return self._data[output_number]['tx_hash']

  def get_tx_o_n(self, output_number):
    """ Return the transaction output number of an unspent 
    output.
    """
    return self._data[output_number]['tx_output_n']

class blockchain_info_poll:
  """ Manages the polling of the currency data.
  """
  def __init__(self, btc_addr):
    self.currency_rate = self.update_currency_rate(btc_addr)

  def update_currency_rate(self, btc_addr = None):
    """ Updates all currency values present on the UI 
    to keep them up to date.

    This is the only function that is actually polled 
    in the whole program. This is done because on weak 
    systems, such as an Raspberry Pi, executing this 
    function too frequently can cause errors.
    """
    poll.stop()
    message('Polling currency rate and/or updating balance!', 'dev')
    try:
      if(btc_addr):
        currency_url = 'https://blockchain.info/ticker'
        balance_url = 'https://blockchain.info/rawaddr/' + btc_addr
        self.currency_rate = json.loads(urlopen(currency_url, timeout = default_wait).read())['EUR']['sell']
        current_balance = json.loads(urlopen(balance_url, timeout = default_wait).read())['final_balance']
        if(0 != current_balance):
          balance_mbtc = '%0.3f' % self.currency_conversion('SAT_MBTC', current_balance)
          balance_euro = '%0.3f' % self.currency_conversion('SAT_EURO', current_balance)
          ui.balance.setText(
              'Current balance:\n'
            + '(including unconfirmed)\n' 
            + str(balance_mbtc)
            + ' Milli-Bitcoin\n'
            + str(current_balance) 
            + ' Satoshi\n'
            + str(balance_euro)
            + ' Euro'
            )
        else:
          ui.balance.setText(
              'Current balance:\n' 
            + 'No money on this address!'
            )
    except Exception as details:
      ui.balance.setText('This application needs a valid internet connection to function as intended!')
      raise Warning('Please check the internet connection! ' + str(details))
    
    if(self.currency_conversion):
      amount_euro = '%0.3f' % self.currency_conversion('SAT_EURO', int(ui.amount.text()))
      fee_euro = '%0.3f' % self.currency_conversion('SAT_EURO', int(ui.fee.text()))
            
      ui.amount_converter.setText(
        'Satoshi = ' 
        + str(amount_euro)
        + ' Euro'
        )
      ui.fee_converter.setText(
        'Satoshi = ' 
        + str(fee_euro)
        + ' Euro'
        )
    else:
      raise Warning('Currency conversion rate not available!')

    if(btc_addr):
      poll.start(default_wait * polling_multiplier, self.update_currency_rate, btc_addr)
    return self.currency_rate

  def currency_conversion(self, conversion_type, currency):
    """ Converts currency depending on `conversion_type`.
    """
    if('SAT_MBTC' == conversion_type):
      return currency / (10 ** 5)
    elif('MBTC_SAT' == conversion_type):
      return currency * (10 ** 5)
    elif('BTC_EURO' == conversion_type):
      return currency * self.currency_rate
    elif('EURO_BTC' == conversion_type):
      return currency / self.currency_rate
    elif('SAT_EURO' == conversion_type):
      return currency / (10 ** 8) * self.currency_rate
    elif('EURO_SAT' == conversion_type):
      return currency * (10 ** 8) / self.currency_rate
    else:
      raise SpellingMistake()

if __name__ == '__main__':
  ## Utility
  timer = timer_class()
  poll = timer_class()

  ## Card / reader
  cardmonitor, cardobserver = observer.start()
  reader = reader_info()

  ## UI
  app = QApplication()
  app.aboutToQuit.connect(close_event)
  ui = UI.load()
  ui.show_window()

  # Start application
  blocksec2go.add_callback(connect = card_connect, disconnect = card_disconnect)
  app.exec_()
