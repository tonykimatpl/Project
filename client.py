import json
import threading
import queue
import pygame
import websocket  # websocket-client library
import math
import random

BOARD_SIZE = 5  # Increased to 5x5
CELL_SIZE = 80  # Adjusted for fit
SIDEBAR_WIDTH = 200  # Space for stats on the side
WINDOW_SIZE = (BOARD_SIZE * CELL_SIZE + SIDEBAR_WIDTH + 40, BOARD_SIZE * CELL_SIZE + 100)  # Extra space
HOLD_TIME_MS = 3000  # 3 seconds
ANIMATION_FPS = 60  # For smooth animation

class GameClient:
    def __init__(self):
        self.ws = None
        self.message_queue = queue.Queue()
        self.player_id = None
        self.symbol = None
        self.game_over = False
        self.winner = None  # Track the winner symbol
        self.board = [[' ' for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
        self.hold_start_time = None
        self.hold_row = None
        self.hold_col = None
        self.hold_progress = 0.0
        self.victory_particles = []
        self.player_scores = {'X': 0, 'O': 0, '△': 0}  # Initialize for all symbols
        self.pulse_time = 0  # For winner text animation

        # Colors
        self.colors = {'X': (255, 100, 100), 'O': (100, 100, 255), '△': (100, 255, 100)}  # Vibrant RGB
        self.base_color = (255, 255, 255)  # White
        self.grid_color = (50, 50, 50)  # Dark gray
        self.text_color = (0, 0, 0)  # Black
        self.hover_color = (220, 220, 220)  # Light gray for hover
        self.bg_gradient_start = (200, 220, 255)  # Light blue
        self.bg_gradient_end = (240, 240, 240)  # Light gray-white
        self.shadow_color = (0, 0, 0, 50)  # Semi-transparent black for shadows
        self.glow_color = (255, 255, 255, 100)  # Semi-transparent white for glow
        self.overlay_color = (0, 0, 0, 150)  # Semi-transparent black for winner overlay

        # Pygame setup
        pygame.init()
        pygame.mixer.init()  # For sounds
        self.screen = pygame.display.set_mode(WINDOW_SIZE, pygame.RESIZABLE)
        pygame.display.set_caption("Deny and Conquer")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("Arial", 24)
        self.big_font = pygame.font.SysFont("Arial", 36, bold=True)
        self.small_font = pygame.font.SysFont("Arial", 18)
        self.winner_font = pygame.font.SysFont("Arial", 48, bold=True)  # New large font for winner screen

        # Load sounds with error handling
        try:
            self.claim_sound = pygame.mixer.Sound('claim.mp3')
            self.victory_sound = pygame.mixer.Sound('victory.mp3')
        except pygame.error as e:
            print(f"Error loading sounds: {e}. Ensure files are in the directory. Using placeholders.")
            # Fallback to silent placeholders if loading fails
            self.claim_sound = pygame.mixer.Sound(buffer=b'\x00\x00' * 1000)
            self.victory_sound = pygame.mixer.Sound(buffer=b'\x00\x00' * 1000)

        # Start WebSocket in a thread
        threading.Thread(target=self.start_websocket, daemon=True).start()

        # Main loop
        self.run()

    def start_websocket(self):
        self.ws = websocket.WebSocketApp("ws://localhost:8765",
                                         on_open=self.on_open,
                                         on_message=self.on_message,
                                         on_error=self.on_error,
                                         on_close=self.on_close)
        self.ws.run_forever()

    def on_open(self, ws):
        pass

    def on_message(self, ws, message):
        self.message_queue.put(message)

    def on_error(self, ws, error):
        self.message_queue.put(json.dumps({"error": str(error)}))

    def on_close(self, ws, close_status_code, close_msg):
        self.message_queue.put(json.dumps({"status": "Connection closed"}))

    def process_messages(self):
        try:
            while not self.message_queue.empty():
                message = self.message_queue.get_nowait()
                data = json.loads(message)

                if 'error' in data:
                    print(f"Error: {data['error']}")
                    pygame.quit()
                    return True  # Signal to quit

                if 'player_id' in data:
                    self.player_id = data['player_id']
                    self.symbol = data['symbol']

                if 'status' in data:
                    if 'board' in data:
                        self.board = data['board']
                        self.reset_hold()
                        self.update_scores()
                    if data['status'] == 'game_over':
                        self.game_over = True
                        self.winner = data.get('winner')
                        print(f"Game Over: Winner {self.winner}")
                        if self.winner == self.symbol:
                            self.create_victory_particles(self.winner)
                            self.victory_sound.play()  # Play victory sound for the local winner
                    elif data['status'] == 'Game aborted: Player disconnected':
                        self.game_over = True
                        print("Game Aborted: Player disconnected.")
                    elif data['status'] == 'Connection closed':
                        return True  # Quit
        except queue.Empty:
            pass
        return False

    def run(self):
        running = True
        while running:
            if self.process_messages():
                running = False
                continue

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.MOUSEBUTTONDOWN and not self.game_over:
                    self.handle_mouse_down(event)
                elif event.type == pygame.MOUSEBUTTONUP and not self.game_over:
                    self.handle_mouse_up(event)
                elif event.type == pygame.VIDEORESIZE:
                    self.screen = pygame.display.set_mode(event.size, pygame.RESIZABLE)
                    global WINDOW_SIZE
                    WINDOW_SIZE = event.size  # Update global size for particles

            # Draw everything
            self.draw()
            pygame.display.flip()
            self.clock.tick(ANIMATION_FPS)

            # Update hold progress if active
            if self.hold_row is not None and self.hold_col is not None:
                elapsed = pygame.time.get_ticks() - self.hold_start_time
                self.hold_progress = min(elapsed / HOLD_TIME_MS, 1.0)

            # Update particles and pulse time
            self.update_particles()
            self.pulse_time += 1

        if self.ws:
            self.ws.close()
        pygame.quit()

    def handle_mouse_down(self, event):
        if event.button == 1:  # Left click
            mx, my = event.pos
            row, col = self.get_cell_from_pos(mx, my)
            if row is not None and col is not None and self.board[row][col] == ' ' and self.symbol:
                self.hold_start_time = pygame.time.get_ticks()
                self.hold_row = row
                self.hold_col = col
                self.hold_progress = 0.0

    def handle_mouse_up(self, event):
        if event.button == 1 and self.hold_row is not None and self.hold_col is not None:
            mx, my = event.pos
            row, col = self.get_cell_from_pos(mx, my)
            if (row, col) == (self.hold_row, self.hold_col) and self.hold_progress >= 1.0:
                self.ws.send(json.dumps({"action": "claim", "row": row, "col": col}))
                self.claim_sound.play()
            self.reset_hold()

    def get_cell_from_pos(self, x, y):
        offset_x, offset_y = 20, 60
        row = (y - offset_y) // CELL_SIZE
        col = (x - offset_x) // CELL_SIZE
        if 0 <= row < BOARD_SIZE and 0 <= col < BOARD_SIZE:
            return row, col
        return None, None

    def draw(self):
        # Gradient background
        for y in range(self.screen.get_height()):
            ratio = y / self.screen.get_height()
            r = int(self.bg_gradient_start[0] + ratio * (self.bg_gradient_end[0] - self.bg_gradient_start[0]))
            g = int(self.bg_gradient_start[1] + ratio * (self.bg_gradient_end[1] - self.bg_gradient_start[1]))
            b = int(self.bg_gradient_start[2] + ratio * (self.bg_gradient_end[2] - self.bg_gradient_start[2]))
            pygame.draw.line(self.screen, (r, g, b), (0, y), (self.screen.get_width(), y))

        # Player label
        label_text = f"Player {self.player_id or '?'} ({self.symbol or '?'})" if self.player_id else "Connecting..."
        label = self.font.render(label_text, True, self.text_color)
        self.screen.blit(label, (20, 10))

        # Status (e.g., Game Over)
        if self.game_over and (self.winner != self.symbol or self.winner is None):
            status_text = "Game Over"
            status = self.font.render(status_text, True, (255, 0, 0))
            self.screen.blit(status, (self.screen.get_width() // 2 - status.get_width() // 2 - SIDEBAR_WIDTH // 2, 10))

        # Draw board
        offset_x, offset_y = 20, 60
        mx, my = pygame.mouse.get_pos()
        hover_row, hover_col = self.get_cell_from_pos(mx, my)

        for i in range(BOARD_SIZE):
            for j in range(BOARD_SIZE):
                rect = pygame.Rect(offset_x + j * CELL_SIZE, offset_y + i * CELL_SIZE, CELL_SIZE, CELL_SIZE)
                
                # Shadow for depth
                shadow_rect = pygame.Rect(rect.x + 2, rect.y + 2, CELL_SIZE, CELL_SIZE)
                pygame.draw.rect(self.screen, self.shadow_color, shadow_rect, border_radius=10)
                
                # Base fill
                if self.board[i][j] != ' ':
                    color = self.colors.get(self.board[i][j], self.base_color)
                else:
                    color = self.base_color
                
                # Hover effect (only if not game over)
                if not self.game_over and self.board[i][j] == ' ' and (i, j) == (hover_row, hover_col):
                    color = self.hover_color
                
                pygame.draw.rect(self.screen, color, rect, border_radius=10)
                
                # Animation if holding
                if (i, j) == (self.hold_row, self.hold_col) and self.hold_progress > 0:
                    target_color = self.colors.get(self.symbol, self.base_color)
                    # Interpolate color
                    r = int(color[0] + self.hold_progress * (target_color[0] - color[0]))
                    g = int(color[1] + self.hold_progress * (target_color[1] - color[1]))
                    b = int(color[2] + self.hold_progress * (target_color[2] - color[2]))
                    anim_color = (r, g, b)
                    
                    # Radial pulse with glow
                    center = (rect.centerx, rect.centery)
                    max_radius = math.sqrt((CELL_SIZE/2)**2 + (CELL_SIZE/2)**2)
                    radius = self.hold_progress * max_radius
                    pygame.draw.circle(self.screen, anim_color, center, radius, width=0)
                    # Glow ring
                    pygame.draw.circle(self.screen, self.glow_color, center, radius + 2, width=2)
                
                # Draw symbol
                if self.board[i][j] != ' ':
                    symbol_text = self.big_font.render(self.board[i][j], True, self.text_color)
                    text_rect = symbol_text.get_rect(center=rect.center)
                    self.screen.blit(symbol_text, text_rect)

                # Grid lines
                pygame.draw.rect(self.screen, self.grid_color, rect, width=2, border_radius=10)

        # Draw player scores on the side (always, even in game over)
        self.draw_scores(offset_x + BOARD_SIZE * CELL_SIZE + 20, 60)

        # Draw winner screen if local player won
        if self.game_over and self.winner == self.symbol:
            self.draw_winner_screen()

        # Draw victory particles (on top of everything)
        for particle in self.victory_particles:
            alpha_color = (*particle['color'][:3], int(particle['alpha']))  # Apply alpha
            pygame.draw.circle(self.screen, alpha_color, (int(particle['x']), int(particle['y'])), int(particle['size']))

    def draw_winner_screen(self):
        # Semi-transparent overlay
        overlay = pygame.Surface((self.screen.get_width(), self.screen.get_height()), pygame.SRCALPHA)
        overlay.fill(self.overlay_color)
        self.screen.blit(overlay, (0, 0))

        # Pulsing "Winner Winner Chicken Dinner!" text
        pulse_scale = 1.0 + 0.1 * math.sin(self.pulse_time / 10)  # Gentle pulse
        winner_color = self.colors.get(self.winner, (255, 255, 0))
        # Color shift: interpolate between winner color and white
        shift_ratio = (math.sin(self.pulse_time / 20) + 1) / 2
        r = int(winner_color[0] + shift_ratio * (255 - winner_color[0]))
        g = int(winner_color[1] + shift_ratio * (255 - winner_color[1]))
        b = int(winner_color[2] + shift_ratio * (255 - winner_color[2]))
        text_color = (r, g, b)

        winner_text = self.winner_font.render("Winner Winner Chicken Dinner!", True, text_color)
        scaled_text = pygame.transform.smoothscale(winner_text, (int(winner_text.get_width() * pulse_scale), int(winner_text.get_height() * pulse_scale)))
        text_rect = scaled_text.get_rect(center=(self.screen.get_width() // 2, self.screen.get_height() // 2 - 50))
        self.screen.blit(scaled_text, text_rect)

        # Subtitle
        subtitle = self.font.render("You Conquered!", True, text_color)
        sub_rect = subtitle.get_rect(center=(self.screen.get_width() // 2, self.screen.get_height() // 2 + 50))
        self.screen.blit(subtitle, sub_rect)

    def draw_scores(self, x, y):
        title = self.font.render("Leaderboard", True, self.text_color)
        self.screen.blit(title, (x, y))
        y += 40

        sorted_scores = sorted(self.player_scores.items(), key=lambda item: item[1], reverse=True)

        for i, (symbol, score) in enumerate(sorted_scores):
            is_leader = i == 0
            prefix = "★ " if is_leader else ""
            score_text = f"{prefix}{symbol}: {score}"
            font = self.small_font if not is_leader else self.font  # Bold for leader
            score_label = font.render(score_text, True, self.colors.get(symbol, self.text_color))
            self.screen.blit(score_label, (x, y))
            y += 30

    def update_scores(self):
        self.player_scores = {'X': 0, 'O': 0, '△': 0}  # Reset
        for row in self.board:
            for cell in row:
                if cell != ' ':
                    self.player_scores[cell] += 1

    def reset_hold(self):
        self.hold_start_time = None
        self.hold_row = None
        self.hold_col = None
        self.hold_progress = 0.0

    def create_victory_particles(self, winner):
        self.victory_particles = []
        winner_color = self.colors.get(winner, (255, 255, 0))  # Default yellow if error
        center_x, center_y = self.screen.get_width() // 2, self.screen.get_height() // 2
        for _ in range(200):  # More particles for cooler effect
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(5, 10)
            self.victory_particles.append({
                'x': center_x,
                'y': center_y,
                'vx': speed * math.cos(angle),
                'vy': speed * math.sin(angle),
                'color': winner_color if random.random() < 0.7 else random.choice(list(self.colors.values())),  # Mostly winner's color
                'size': random.randint(3, 8),
                'alpha': 255,  # Start fully opaque
                'life': random.randint(100, 200),  # Shorter life for burst effect
                'type': random.choice(['circle', 'star'])  # Variety: circles or stars
            })

    def update_particles(self):
        for particle in self.victory_particles[:]:
            particle['x'] += particle['vx']
            particle['y'] += particle['vy']
            particle['vy'] += 0.2  # Gravity
            particle['life'] -= 1
            particle['size'] = max(1, particle['size'] - 0.1)
            particle['alpha'] = max(0, particle['alpha'] - 2)  # Fade out
            if particle['life'] <= 0 or particle['y'] > self.screen.get_height() or particle['alpha'] <= 0:
                self.victory_particles.remove(particle)

if __name__ == "__main__":
    GameClient()
