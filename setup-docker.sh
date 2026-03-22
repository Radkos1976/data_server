#!/bin/bash

# ============================================================
# Setup Docker z interaktywną konfiguracją ścieżek
# ============================================================
# Skrypt pyta o ścieżki dla danych (PostgreSQL, Redis, CSV import)
# i pamiętać je na przyszłość
#
# Użycie:
#   chmod +x setup-docker.sh
#   ./setup-docker.sh

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$PROJECT_ROOT/.env.docker.paths"

# Kolory dla wiadomości
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ============================================================
# Funkcje pomocnicze
# ============================================================

print_header() {
    echo -e "\n${BLUE}=== $1 ===${NC}\n"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

# ============================================================
# Wczytanie poprzedniej konfiguracji (jeśli istnieje)
# ============================================================

load_config() {
    if [ -f "$CONFIG_FILE" ]; then
        source "$CONFIG_FILE"
        return 0
    else
        return 1
    fi
}

# ============================================================
# Zapis konfiguracji
# ============================================================

save_config() {
    cat > "$CONFIG_FILE" << EOF
# Konfiguracja ścieżek dla Docker setup
# Data ostatniej modyfikacji: $(date)
export POSTGRES_DATA_PATH="$POSTGRES_DATA_PATH"
export REDIS_DATA_PATH="$REDIS_DATA_PATH"
export IMPORTS_INPUT_PATH="$IMPORTS_INPUT_PATH"
EOF
    print_success "Konfiguracja zapisana w: $CONFIG_FILE"
}

# ============================================================
# Walidacja i tworzenie folderów
# ============================================================

validate_and_create_paths() {
    local path="$1"
    local name="$2"
    
    if [ -z "$path" ]; then
        print_error "$name: ścieżka nie może być pusta"
        return 1
    fi
    
    # Rozwijanie ~ na home directory
    path="${path/#\~/$HOME}"
    
    # Tworzenie folderu jeśli nie istnieje
    if ! mkdir -p "$path" 2>/dev/null; then
        print_error "Nie udało się utworzyć folderu: $path"
        return 1
    fi
    
    # Sprawdzenie uprawnień zapisu
    if ! touch "$path/.test_write" 2>/dev/null; then
        print_error "Brak uprawnień do zapisu w: $path"
        rm -f "$path/.test_write" 2>/dev/null
        return 1
    fi
    rm -f "$path/.test_write"
    
    print_success "$name: $(readlink -f "$path")"
    return 0
}

# ============================================================
# Pytanie o ścieżkę (z opcją zaakceptowania domyślnej)
# ============================================================

ask_for_path() {
    local prompt="$1"
    local default="$2"
    local answer
    
    if [ -n "$default" ]; then
        read -p "$(echo -e "${YELLOW}$prompt${NC}") [domyślnie: $default]: " answer
        [ -z "$answer" ] && answer="$default"
    else
        read -p "$(echo -e "${YELLOW}$prompt${NC}"): " answer
    fi
    
    echo "$answer"
}

# ============================================================
# Menu główne
# ============================================================

show_menu() {
    print_header "Setup Docker - Data Server"
    
    echo "Opcje:"
    echo "  1) Skonfiguruj nowe ścieżki"
    echo "  2) Użyj poprzedniej konfiguracji (jeśli istnieje)"
    echo "  3) Zmień ścieżki"
    echo "  4) Wyjdź"
    echo ""
    read -p "Wybierz opcję [1-4]: " choice
    
    case $choice in
        1)
            configure_new_paths
            ;;
        2)
            if load_config; then
                print_success "Załadowana poprzednia konfiguracja"
                show_current_config
                start_docker
            else
                print_warning "Nie znaleziono poprzedniej konfiguracji"
                configure_new_paths
            fi
            ;;
        3)
            if load_config; then
                show_current_config
                configure_paths
                save_config
                start_docker
            else
                print_warning "Nie znaleziono poprzedniej konfiguracji"
                configure_new_paths
            fi
            ;;
        4)
            echo "Wyjście."
            exit 0
            ;;
        *)
            print_error "Niepoprawna opcja"
            show_menu
            ;;
    esac
}

# ============================================================
# Konfiguracja nowych ścieżek
# ============================================================

configure_new_paths() {
    configure_paths
    save_config
    start_docker
}

# ============================================================
# Interaktywna konfiguracja ścieżek
# ============================================================

configure_paths() {
    print_header "Konfiguracja ścieżek"
    
    # Domyślne ścieżki
    local default_postgres="$PROJECT_ROOT/data/postgres_data"
    local default_redis="$PROJECT_ROOT/data/redis_data"
    local default_imports="$PROJECT_ROOT/data/imports_input"
    
    # Pytania o ścieżki
    echo ""
    echo "Podaj ścieżki do przechowywania danych."
    echo "Foldery będą utworzone automatycznie."
    echo ""
    
    POSTGRES_DATA_PATH=$(ask_for_path "Ścieżka do danych PostgreSQL:" "$default_postgres")
    
    REDIS_DATA_PATH=$(ask_for_path "Ścieżka do danych Redis:" "$default_redis")
    
    IMPORTS_INPUT_PATH=$(ask_for_path "Ścieżka do importu CSV:" "$default_imports")
    
    # Walidacja i tworzenie folderów
    echo ""
    print_header "Weryfikacja ścieżek"
    
    validate_and_create_paths "$POSTGRES_DATA_PATH" "PostgreSQL" || return 1
    validate_and_create_paths "$REDIS_DATA_PATH" "Redis" || return 1
    validate_and_create_paths "$IMPORTS_INPUT_PATH" "CSV import" || return 1
}

# ============================================================
# Wyświetlenie obecnej konfiguracji
# ============================================================

show_current_config() {
    echo ""
    print_header "Obecna konfiguracja"
    
    echo "PostgreSQL data:  $POSTGRES_DATA_PATH"
    echo "Redis data:       $REDIS_DATA_PATH"
    echo "CSV import:       $IMPORTS_INPUT_PATH"
    echo ""
}

# ============================================================
# Uruchomienie Docker-a
# ============================================================

start_docker() {
    echo ""
    read -p "Czy chcesz uruchomić Docker? (y/n) [y]: " start_choice
    start_choice="${start_choice:-y}"
    
    if [[ "$start_choice" == "y" || "$start_choice" == "Y" ]]; then
        print_header "Uruchamianie Docker Compose"
        
        # Export zmiennych aby były dostępne dla docker-compose
        export POSTGRES_DATA_PATH
        export REDIS_DATA_PATH
        export IMPORTS_INPUT_PATH
        
        # Przygowanie docker-compose-override.yml z ścieżkami
        cat > "$PROJECT_ROOT/docker-compose.override.yml" << EOF
# Override ścieżek dla docker-compose (automatycznie generowany)
# Data: $(date)
# EDYTUJ SETUP-DOCKER.SH, A NIE TEN PLIK

services:
  postgres:
    volumes:
      - $POSTGRES_DATA_PATH:/var/lib/postgresql/data
  
  redis:
    volumes:
      - $REDIS_DATA_PATH:/data
  
  app:
    volumes:
      - $IMPORTS_INPUT_PATH:/data/imports_input
      - ./data/app_logs:/app/logs
EOF
        
        print_success "Wygenerowany docker-compose.override.yml"
        
        echo ""
        echo "Komendy Docker:"
        echo "  docker-compose up --build       (uruchomienie + build)"
        echo "  docker-compose up               (bez build)"
        echo "  docker-compose down             (zatrzymanie)"
        echo "  docker-compose logs -f app      (logi aplikacji)"
        echo ""
        
        read -p "Wpisz komendę docker-compose [up --build]: " docker_cmd
        docker_cmd="${docker_cmd:-up --build}"
        
        cd "$PROJECT_ROOT"
        docker-compose $docker_cmd
    else
        print_success "Skonfigurowano ścieżki, ale Docker nie został uruchomiony"
        echo "Aby uruchomić Docker później, wykonaj:"
        echo "  cd $PROJECT_ROOT"
        echo "  docker-compose up --build"
    fi
}

# ============================================================
# Główny punkt wejścia
# ============================================================

main() {
    # Sprawdzenie czy docker-compose jest zainstalowany
    if ! command -v docker-compose &> /dev/null; then
        print_error "docker-compose nie znaleziony. Zainstaluj Docker Desktop lub docker-compose."
        exit 1
    fi
    
    # Sprawdzenie czy Docker daemon jest uruchomiony
    if ! docker info &> /dev/null; then
        print_error "Docker daemon nie jest uruchomiony. Uruchom Docker Desktop lub demon dockera."
        exit 1
    fi
    
    # Jeśli skrypt uruchomiony z argumentem "--auto", użyj poprzedniej konfiguracji
    if [ "$1" == "--auto" ]; then
        if load_config; then
            print_header "Setup Docker - Data Server (AUTO MODE)"
            show_current_config
            print_success "Używam poprzedniej konfiguracji"
            
            export POSTGRES_DATA_PATH
            export REDIS_DATA_PATH
            export IMPORTS_INPUT_PATH
            
            cat > "$PROJECT_ROOT/docker-compose.override.yml" << EOF
services:
  postgres:
    volumes:
      - $POSTGRES_DATA_PATH:/var/lib/postgresql/data
  redis:
    volumes:
      - $REDIS_DATA_PATH:/data
  app:
    volumes:
      - $IMPORTS_INPUT_PATH:/data/imports_input
      - ./data/app_logs:/app/logs
EOF
            
            cd "$PROJECT_ROOT"
            docker-compose up --build
        else
            print_error "Brak poprzedniej konfiguracji. Uruchom bez --auto"
            exit 1
        fi
    else
        # Zwykły tryb interaktywny
        if load_config; then
            show_current_config
            show_menu
        else
            configure_new_paths
        fi
    fi
}

# Uruchomienie
main "$@"
