#include <SPI.h>
#include <Ethernet.h>
#include <EthernetUDP.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

// --- НАСТРОЙКИ ПУЛЬТА ---
const char* DEVICE_ID = "ID:T1:PT:N1";   // T1 – номер стола, PT – пульт, N1 – номер пульта
const int TABLE_NUM = 1;
const int REMOTE_NUM = 1;

// Пины кнопок
const int PIN_Y_BTN = 22;   // жёлтая
const int PIN_R_BTN = 23;   // красная
const int PIN_G_BTN = 24;   // зелёная
const int PIN_E_BTN = 25;   // аварийная

// Пины джойстика (аналоговые)
const int PIN_JOY_X = A1;
const int PIN_JOY_Y = A0;

// Светодиоды (управляются сервером)
const int PIN_LED_Y = 2;
const int PIN_LED_G = 3;
const int PIN_LED_B = 4;
const int PIN_LED_R = 5;

// Адрес и порты сервера
byte mac[] = { 0xDE, 0xAD, 0xBE, 0xEF, 0xFE, 0x09 };
IPAddress server(192, 168, 0, 100);
const unsigned int SERVER_PORT = 8888;
const unsigned int LOCAL_PORT = 8890;

EthernetUDP Udp;
LiquidCrystal_I2C lcd(0x27, 20, 4);

unsigned long lastStatusSend = 0;
const unsigned long STATUS_INTERVAL = 100; // 100 мс
unsigned long lastRegSend = 0;
const unsigned long REG_INTERVAL = 30000;

// Предыдущие состояния (для отладки)
int lastE = 0, lastR = 0, lastY = 0, lastG = 0;
int lastJX = -1, lastJY = -1;

void setup() {
  pinMode(PIN_Y_BTN, INPUT_PULLUP);
  pinMode(PIN_R_BTN, INPUT_PULLUP);
  pinMode(PIN_G_BTN, INPUT_PULLUP);
  pinMode(PIN_E_BTN, INPUT_PULLUP);
  
  pinMode(PIN_LED_R, OUTPUT);
  pinMode(PIN_LED_Y, OUTPUT);
  pinMode(PIN_LED_G, OUTPUT);
  pinMode(PIN_LED_B, OUTPUT);

  Serial.begin(9600);
  Ethernet.begin(mac);
  delay(1000);
  Udp.begin(LOCAL_PORT);
  
  lcd.init();
  lcd.backlight();
  lcd.clear();

  // Получаем IP-адрес пульта
  IPAddress ip = Ethernet.localIP();
  String ipStr = String(ip[0]) + "." + String(ip[1]) + "." + String(ip[2]) + "." + String(ip[3]);

  // Первая строка: слева "Table X", справа IP
  lcd.setCursor(0, 0);
  lcd.print("Table");
  lcd.print(TABLE_NUM);
  
  int ipPos = 20 - ipStr.length();
  if (ipPos < 0) ipPos = 0; // на всякий случай
  lcd.setCursor(ipPos, 0);
  lcd.print(ipStr);

  // Вторая строка: статус
  lcd.setCursor(0, 1);
  lcd.print("Ready");
  
  Serial.println("Remote control started");
  sendRegistration();
  lastRegSend = millis();
}

void sendRegistration() {
  Udp.beginPacket(server, SERVER_PORT);
  Udp.write(DEVICE_ID);
  Udp.endPacket();
  Serial.println("Registration sent");
}

void sendStatus() {
  // Чтение кнопок (1 — нажата, 0 — отпущена)
  int e = digitalRead(PIN_E_BTN);
  int r = !digitalRead(PIN_R_BTN);
  int y = !digitalRead(PIN_Y_BTN);
  int g = !digitalRead(PIN_G_BTN);
  int jx = analogRead(PIN_JOY_X);
  int jy = analogRead(PIN_JOY_Y);

  String status = "T" + String(TABLE_NUM) + ":PT:N" + String(REMOTE_NUM) +
                  ":E" + String(e) +
                  ":R" + String(r) +
                  ":Y" + String(y) +
                  ":G" + String(g) +
                  ":JX" + String(jx) +
                  ":JY" + String(jy);
  
  Udp.beginPacket(server, SERVER_PORT);
  Udp.write(status.c_str());
  Udp.endPacket();
  
  Serial.print("Status sent: ");
  Serial.println(status);
}

void setLED(char color, int state) {
  int pin = -1;
  if (color == 'R') pin = PIN_LED_R;
  else if (color == 'Y') pin = PIN_LED_Y;
  else if (color == 'G') pin = PIN_LED_G;
  else if (color == 'B') pin = PIN_LED_B;

  if (pin != -1) {
    digitalWrite(pin, state ? HIGH : LOW);
    Serial.print("Set LED ");
    Serial.print(color);
    Serial.print(" to ");
    Serial.println(state);
  }
}

void setLCDLine(int row, String text) {
  if (row < 1 || row > 4) return;
  lcd.setCursor(0, row - 1);
  // Очищаем строку
  for (int i = 0; i < 20; i++) lcd.print(' ');
  lcd.setCursor(0, row - 1);
  lcd.print(text);
}

void loop() {
  int packetSize = Udp.parsePacket();
  if (packetSize) {
    char buffer[64];
    int len = Udp.read(buffer, sizeof(buffer) - 1);
    if (len > 0) {
      buffer[len] = '\0';
      String cmd = String(buffer);
      cmd.trim();
      Serial.print("Received command: ");
      Serial.println(cmd);

      if (cmd.length() == 2) {
        char color = cmd.charAt(0);
        int state = cmd.substring(1).toInt();
        setLED(color, state);
      }
      else if (cmd.startsWith("LCD")) {
        int colonIdx = cmd.indexOf(':');
        if (colonIdx > 3) {
          int row = cmd.substring(3, colonIdx).toInt();
          if (row >= 1 && row <= 4) {
            String text = cmd.substring(colonIdx + 1);
            setLCDLine(row, text);
          }
        }
      }
      else if (cmd == "CLR") {
        lcd.clear();
        Serial.println("LCD cleared");
      }
    }
  }

  if (millis() - lastStatusSend >= STATUS_INTERVAL) {
    sendStatus();
    lastStatusSend = millis();
  }

  if (millis() - lastRegSend >= REG_INTERVAL) {
    sendRegistration();
    lastRegSend = millis();
  }
}
