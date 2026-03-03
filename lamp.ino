#include <SPI.h>
#include <Ethernet.h>
#include <EthernetUDP.h>

// --- НАСТРОЙКИ ---
const char* DEVICE_ID = "ID:T4:DL:N2";
const int TABLE_NUM = 1;
const int DEVICE_NUM = 1;

const int PIN_Y = 2;
const int PIN_G = 3;
const int PIN_B = 4;
const int PIN_R = 5;

byte mac[] = { 0xDE, 0xAD, 0xBE, 0xEF, 0xFE, 0x08 };
IPAddress server(192, 168, 0, 100);
const unsigned int SERVER_PORT = 8888;
const unsigned int LOCAL_PORT = 8889;

EthernetUDP Udp;

unsigned long lastStatusSend = 0;
const unsigned long STATUS_INTERVAL = 10000; // 10 сек

unsigned long lastRegSend = 0;
const unsigned long REG_INTERVAL = 30000;    // 30 сек

void setup() {
  pinMode(PIN_R, OUTPUT); pinMode(PIN_Y, OUTPUT);
  pinMode(PIN_G, OUTPUT); pinMode(PIN_B, OUTPUT);
  Serial.begin(9600);

  Ethernet.begin(mac);
  delay(1000);

  Udp.begin(LOCAL_PORT);
  Serial.print("UDP started on port ");
  Serial.println(LOCAL_PORT);

  sendRegistration();
  lastRegSend = millis();
}

void sendRegistration() {
  Udp.beginPacket(server, SERVER_PORT);
  Udp.write(DEVICE_ID);
  Udp.endPacket();
  Serial.println("Registration sent");
}

void sendFullStatus() {
  String status = "T" + String(TABLE_NUM) + ":DL:N" + String(DEVICE_NUM) +
                  ":AC:R" + String(digitalRead(PIN_R)) +
                  ":Y" + String(digitalRead(PIN_Y)) +
                  ":G" + String(digitalRead(PIN_G)) +
                  ":B" + String(digitalRead(PIN_B));
  Udp.beginPacket(server, SERVER_PORT);
  Udp.write(status.c_str());
  Udp.endPacket();
  Serial.print("Status sent: ");
  Serial.println(status);
}

void setColor(char color, int state) {
  int pin = -1;
  if (color == 'R') pin = PIN_R;
  else if (color == 'Y') pin = PIN_Y;
  else if (color == 'G') pin = PIN_G;
  else if (color == 'B') pin = PIN_B;

  if (pin != -1) {
    digitalWrite(pin, state);
    Serial.print("Set color ");
    Serial.print(color);
    Serial.print(" to ");
    Serial.println(state);
    sendFullStatus();
  }
}

void loop() {
  int packetSize = Udp.parsePacket();
  if (packetSize) {
    char buffer[32];
    int len = Udp.read(buffer, sizeof(buffer) - 1);
    if (len > 0) {
      buffer[len] = '\0';
      String cmd = String(buffer);
      cmd.trim();
      Serial.print("Received: ");
      Serial.println(cmd);

      if (cmd == "1111") {
        digitalWrite(PIN_R, HIGH);
        digitalWrite(PIN_Y, HIGH);
        digitalWrite(PIN_G, HIGH);
        digitalWrite(PIN_B, HIGH);
        sendFullStatus();
      }
      else if (cmd == "0000") {
        digitalWrite(PIN_R, LOW);
        digitalWrite(PIN_Y, LOW);
        digitalWrite(PIN_G, LOW);
        digitalWrite(PIN_B, LOW);
        sendFullStatus();
      }
      else if (cmd.length() == 2) {
        char color = cmd.charAt(0);
        int state = cmd.substring(1).toInt();
        setColor(color, state);
      }
    }
  }

  if (millis() - lastStatusSend >= STATUS_INTERVAL) {
    sendFullStatus();
    lastStatusSend = millis();
  }

  if (millis() - lastRegSend >= REG_INTERVAL) {
    sendRegistration();
    lastRegSend = millis();
  }
}
