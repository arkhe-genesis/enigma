// SPDX-FileCopyrightText: 2026 Kevin Kelm (https://madgoatlabs.com)
// SPDX-License-Identifier: MIT

// Board.cpp

#include "Board.h"
#include "Config.h"
#include "EnigmaLogger.h"
#include "BoardSW14.h"
#include "BoardQD04.h"
#include "BoardAN08.h"

// Static member initialization
BoardVariant Board::_boardTypeNum = BoardVariant::VARIANT_UNKNOWN;
uint8_t      Board::_address      = 0;
Board*       Board::_board        = nullptr;
char         Board::_boardType[5] = "";
char         Board::_boardID[MAX_BOARDID_LEN] = "";

Board::Board() {
    _stateChangeCallback = nullptr;
    _address = Config::detectBoardAddress();
}

Board::~Board() {
}

void Board::setBoardVariant(BoardVariant bv) {
  _boardTypeNum = bv;
}

Board* Board::newInstance(BoardVariant bv) {
  _board = nullptr;
  
  switch (bv) {
    case VARIANT_SW14:
      _board = new BoardSW14();
      break;
      
    case VARIANT_BM16:
      EnigmaLogger::error("***NO VARIANT_BM16 IMPLEMENTATION");
      break;
      
    case VARIANT_AN08:
      _board = new BoardAN08();
      break;
      
    case VARIANT_QD04:
      _board = new BoardQD04();
      break;
      
    case VARIANT_UD08:
      EnigmaLogger::error("***NO VARIANT_UD08 IMPLEMENTATION");
      break;
      
    case VARIANT_SC16:
      EnigmaLogger::error("***NO VARIANT_SC16 IMPLEMENTATION");
      break;
      
    case VARIANT_DC04:
      EnigmaLogger::error("***NO VARIANT_DC04 IMPLEMENTATION");
      break;
      
    case VARIANT_RL16:
      EnigmaLogger::error("***NO VARIANT_RL16 IMPLEMENTATION");
      break;
      
    case VARIANT_LC04:
      EnigmaLogger::error("***NO VARIANT_LC04 IMPLEMENTATION");
      break;
      
    case VARIANT_AU04:
      EnigmaLogger::error("***NO VARIANT_AU04 IMPLEMENTATION");
      break;
      
    case VARIANT_AC08:
      EnigmaLogger::error("***NO VARIANT_AC08 IMPLEMENTATION");
      break;
      
    case VARIANT_MO04:
      EnigmaLogger::error("***NO VARIANT_MO04 IMPLEMENTATION");
      break;
      
    default:
      EnigmaLogger::error("***UNKNOWN BOARD VARIANT %d\n", bv);
      break;
  }

  if (_board != nullptr) {
    _boardTypeNum = _board->getTypeNum();
  }
  
  return _board;
}
