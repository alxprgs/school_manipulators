#include <SPI.h>
#include <Ethernet.h>
#include <EthernetUDP.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

const int TABLE_NUM = 1;
const int REMOTE_NUM = 1;          // номер пульта (1..4)

const int PIN_Y_BTN = 22;   // жёлтая - смена манипулятора
const int PIN_R_BTN = 23;   // красная - слой назад
const int PIN_G_BTN = 24;   // зелёная - слой вперёд
const int PIN_E_BTN = 25;   // аварийная

const int PIN_JOY_X = A1;
const int PIN_JOY_Y = A0;

const int PIN_LED_Y = 2;
const int PIN_LED_G = 3;
const int PIN_LED_B = 4;
const int PIN_LED_R = 5;

byte mac[] = { 0xDE, 0xAD, 0xBE, 0xEF, 0xFE, 0x00 }; // последний байт будет заменён
IPAddress server(192, 168, 0, 100);
const unsigned int SERVER_PORT = 8888;
const unsigned int LOCAL_PORT = 8890;

EthernetUDP Udp;
LiquidCrystal_I2C lcd(0x27, 20, 4);
char device_id[20];                // "ID:T<таблица>:PT:N<пульт>"

unsigned long lastStatusSend = 0;
const unsigned long STATUS_INTERVAL = 100;

int lastY = 1, lastR = 1, lastG = 1, lastE = 1; // для edge detection (PULLUP = 1 когда отпущена)

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

  // Формируем идентификатор пульта
  sprintf(device_id, "ID:T%d:PT:N%d", TABLE_NUM, REMOTE_NUM);

  // Последний байт MAC для пультов (9..12)
  mac[5] = 9 + (REMOTE_NUM - 1);   // 1 → 0x09, 2 → 0x0A, 3 → 0x0B, 4 → 0x0C

  Ethernet.begin(mac);
  delay(1000);
  Udp.begin(LOCAL_PORT);
  
  lcd.init();
  lcd.backlight();
  lcd.clear();

  IPAddress ip = Ethernet.localIP();
  String ipStr = String(ip[0])+"."+String(ip[1])+"."+String(ip[2])+"."+String(ip[3]);

  lcd.setCursor(0, 0);
  lcd.print("Table"); lcd.print(TABLE_NUM);
  lcd.setCursor(20 - ipStr.length(), 0);
  lcd.print(ipStr);

  lcd.setCursor(0, 1);
  lcd.print("Ready");

  Serial.println("Remote started");
  sendRegistration();
}

void sendRegistration() {
  Udp.beginPacket(server, SERVER_PORT);
  Udp.write(device_id);
  Udp.endPacket();
}

void sendSpecial(const char* cmd) {
  Udp.beginPacket(server, SERVER_PORT);
  Udp.write(cmd);
  Udp.endPacket();
  Serial.print("Special sent: "); Serial.println(cmd);
}

void sendStatus() {
  int e = digitalRead(PIN_E_BTN);
  int r = !digitalRead(PIN_R_BTN);
  int y = !digitalRead(PIN_Y_BTN);
  int g = !digitalRead(PIN_G_BTN);
  int jx = analogRead(PIN_JOY_X);
  int jy = analogRead(PIN_JOY_Y);

  String status = "T" + String(TABLE_NUM) + ":PT:N" + String(REMOTE_NUM) +
                  ":E" + String(e) + ":R" + String(r) + ":Y" + String(y) +
                  ":G" + String(g) + ":JX" + String(jx) + ":JY" + String(jy);

  Udp.beginPacket(server, SERVER_PORT);
  Udp.write(status.c_str());
  Udp.endPacket();
}

void setLED(char color, int state) { /* как было */ 
  // ... (оставил твой оригинальный setLED)
  int pin = -1;
  if (color == 'R') pin = PIN_LED_R;
  else if (color == 'Y') pin = PIN_LED_Y;
  else if (color == 'G') pin = PIN_LED_G;
  else if (color == 'B') pin = PIN_LED_B;
  if (pin != -1) digitalWrite(pin, state ? HIGH : LOW);
}

void setLCDLine(int row, String text) {
  if (row < 1 || row > 4) return;
  lcd.setCursor(0, row-1);
  for (int i=0; i<20; i++) lcd.print(' ');
  lcd.setCursor(0, row-1);
  lcd.print(text);
}

void updateLocalLEDs(int e, int jx, int jy) {
  bool emergency = (e == 0);
  bool moving = (abs(jx - 512) > 40 || abs(jy - 512) > 40);

  digitalWrite(PIN_LED_R, emergency ? HIGH : LOW);
  digitalWrite(PIN_LED_Y, moving ? HIGH : LOW);
  digitalWrite(PIN_LED_G, (!emergency && !moving) ? HIGH : LOW);
  // синий остаётся от сервера
}

void loop() {
  int packetSize = Udp.parsePacket();
  if (packetSize) {
    char buffer[64];
    int len = Udp.read(buffer, sizeof(buffer)-1);
    if (len > 0) {
      buffer[len] = '\0';
      String cmd = String(buffer);
      cmd.trim();

      if (cmd.length() == 2) {
        char color = cmd.charAt(0);
        int state = cmd.substring(1).toInt();
        setLED(color, state);
      }
      else if (cmd.startsWith("LCD")) {
        int first = cmd.indexOf(':');
        int second = cmd.indexOf(':', first + 1);
        if (second > first) {
          int row = cmd.substring(first + 1, second).toInt();
          String text = cmd.substring(second + 1);
          setLCDLine(row, text);
        }
      }
      else if (cmd == "CLR") {
        lcd.clear();
      }
      else if (cmd.startsWith("LAYER:")) {
        String l = cmd.substring(6);
        setLCDLine(3, "Layer: " + l);
      }
    }
  }

  // Edge detection + специальные команды
  int y = !digitalRead(PIN_Y_BTN);
  int r = !digitalRead(PIN_R_BTN);
  int g = !digitalRead(PIN_G_BTN);
  int e = digitalRead(PIN_E_BTN);
  int jx = analogRead(PIN_JOY_X);
  int jy = analogRead(PIN_JOY_Y);

  if (y && !lastY) sendSpecial("SWITCH_MP");
  if (r && !lastR) sendSpecial("LAYER_MINUS");
  if (g && !lastG) sendSpecial("LAYER_PLUS");

  lastY = y; lastR = r; lastG = g; lastE = e;

  updateLocalLEDs(e, jx, jy);

  if (millis() - lastStatusSend >= STATUS_INTERVAL) {
    sendStatus();
    lastStatusSend = millis();
  }
}