import asyncio
import websockets
import json
import random

# Game configuration constants
BOARD_SIZE = 5  # 5x5 board
SYMBOLS = ['X', 'O', '△']  # Available symbols for up to 3 players

# Shared game state
connected = set()  # Set of connected websockets
players = {}  # websocket -> {'id': int, 'symbol': str}
player_id_counter = 1
board = None  # Will be initialized when game starts
game_started = False
game_over = False
winner = None

# Lock for thread-safe access to shared state
lock = asyncio.Lock()

# Broadcasts a message to all connected clients
async def broadcast(message):
    for conn in list(connected):
        try:
            await conn.send(json.dumps(message))
        except websockets.ConnectionClosed:
            pass  # Ignore closed connections

# Checks for a winner (row, column, diagonal) or tie (board full)
def check_winner():
    global winner
    # Check rows
    for row in board:
        if all(cell == row[0] and cell != ' ' for cell in row):
            return row[0]
    # Check columns
    for col in range(BOARD_SIZE):
        if all(board[row][col] == board[0][col] and board[0][col] != ' ' for row in range(BOARD_SIZE)):
            return board[0][col]
    # Check diagonals
    if all(board[i][i] == board[0][0] and board[0][0] != ' ' for i in range(BOARD_SIZE)):
        return board[0][0]
    if all(board[i][BOARD_SIZE - 1 - i] == board[0][BOARD_SIZE - 1] and board[0][BOARD_SIZE - 1] != ' ' for i in range(BOARD_SIZE)):
        return board[0][BOARD_SIZE - 1]
    
    # Check for tie: board full without winner
    if all(cell != ' ' for row in board for cell in row):
        # Count scores to determine winner by most cells
        scores = {'X': 0, 'O': 0, '△': 0}
        for row in board:
            for cell in row:
                if cell != ' ':
                    scores[cell] += 1
        max_score = max(scores.values())
        winners = [symbol for symbol, score in scores.items() if score == max_score]
        if len(winners) == 1:
            return winners[0]  # Single winner with most cells
        else:
            return None  # True tie, no winner
    
    return None  # No winner yet

# Handler for each WebSocket connection
async def handler(websocket):
    global player_id_counter, board, game_started, game_over, winner

    async with lock:
        if len(connected) >= len(SYMBOLS):
            await websocket.close(1008, "Game is full")
            return

        connected.add(websocket)
        player = {'id': player_id_counter, 'symbol': SYMBOLS[player_id_counter - 1]}
        players[websocket] = player
        player_id_counter += 1

    try:
        # Send player info to the new player
        await websocket.send(json.dumps({"player_id": player['id'], "symbol": player['symbol']}))
        
        # Update all players with connected players list
        connected_players = [{"id": p['id'], "symbol": p['symbol']} for p in players.values()]
        await broadcast({"connected_players": connected_players})
        
        async with lock:
            # Start game if at least 2 players and not started
            if len(connected) >= 2 and not game_started:
                game_started = True
                board = [[' ' for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]  # Initialize board here
                await broadcast({"status": "Game started!", "board": board})

        # If the game is already started, send the current state to the new player
        if game_started:
            await websocket.send(json.dumps({"status": "Game started!", "board": board}))
            if game_over:
                await websocket.send(json.dumps({"status": "game_over", "winner": winner}))

        # Listen for messages from this player
        async for message in websocket:
            data = json.loads(message)
            if data.get("action") == "claim" and game_started and not game_over:
                row = data["row"]
                col = data["col"]
                async with lock:  # Add lock for move to prevent race conditions
                    if 0 <= row < BOARD_SIZE and 0 <= col < BOARD_SIZE and board[row][col] == ' ':
                        board[row][col] = player['symbol']
                        # Broadcast updated board
                        await broadcast({"status": "update", "board": board})
                        # Check for winner
                        winner_check = check_winner()
                        if winner_check:
                            winner = winner_check
                            game_over = True
                            await broadcast({"status": "game_over", "winner": winner})
                        elif all(cell != ' ' for row in board for cell in row):
                            # Board full, already handled in check_winner
                            pass

    except websockets.ConnectionClosed:
        pass
    finally:
        async with lock:
            connected.discard(websocket)
            if websocket in players:
                del players[websocket]
            
            # Update connected players
            connected_players = [{"id": p['id'], "symbol": p['symbol']} for p in players.values()]
            await broadcast({"connected_players": connected_players})
            
            # If a player disconnects during game, abort if fewer than 2 players
            if game_started and not game_over and len(connected) < 2:
                game_over = True
                await broadcast({"status": "Game aborted: Player disconnected"})
            
            # Reset game if all players disconnect
            if len(connected) == 0:
                player_id_counter = 1
                board = None
                game_started = False
                game_over = False
                winner = None

# Start the WebSocket server
async def main():
    async with websockets.serve(handler, "localhost", 8765):
        await asyncio.Future()  # Run forever

if __name__ == "__main__":
    asyncio.run(main())
