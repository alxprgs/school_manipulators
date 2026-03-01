#include <SPI.h>
#include <Ethernet.h>

// --- НАСТРОЙКИ ---
const char* DEVICE_ID = "ID:T1:DL:N1"; 
const int TABLE_NUM = 1;
const int DEVICE_NUM = 1;

const int PIN_Y = 2;
const int PIN_G = 3;
const int PIN_B = 4;
const int PIN_R = 5;

byte mac[] = { 0xDE, 0xAD, 0xBE, 0xEF, 0xFE, 0x02 };
IPAddress server(192, 168, 1, 100);
EthernetClient client;

void setup() {
  pinMode(PIN_R, OUTPUT); pinMode(PIN_Y, OUTPUT);
  pinMode(PIN_G, OUTPUT); pinMode(PIN_B, OUTPUT);
  Serial.begin(9600);
  Ethernet.begin(mac);
  delay(1000);
  connectToServer();
}

void sendFullStatus() {
  // Формат 2.1: T1:DL:N1:AC:R0:Y0:G0:B0
  client.print("T"); client.print(TABLE_NUM);
  client.print(":DL:N"); client.print(DEVICE_NUM);
  client.print(":AC:R"); client.print(digitalRead(PIN_R));
  client.print(":Y"); client.print(digitalRead(PIN_Y));
  client.print(":G"); client.print(digitalRead(PIN_G));
  client.print(":B"); client.println(digitalRead(PIN_B));
}

void connectToServer() {
  if (client.connect(server, 8888)) {
    client.println(DEVICE_ID);
    sendFullStatus();
  }
}

void loop() {
  if (!client.connected()) connectToServer();

  if (client.available()) {
    String cmd = client.readStringUntil('\n');
    cmd.trim();

    if (cmd == "CS:HS") {
      client.print("T"); client.print(TABLE_NUM);
      client.print(":DL:N"); client.print(DEVICE_NUM);
      client.println(":HS:OK");
    } 
    // Обработка CS:S:CR:S1 (Установка цвета)
    else if (cmd.startsWith("CS:S:C")) {
      char color = cmd.charAt(6); // R, Y, G, B
      int state = cmd.substring(9).toInt(); // 1 или 0
      
      int pin = -1;
      if (color == 'R') pin = PIN_R;
      else if (color == 'Y') pin = PIN_Y;
      else if (color == 'G') pin = PIN_G;
      else if (color == 'B') pin = PIN_B;

      if (pin != -1) {
        digitalWrite(pin, state);
        // Ответ: T1:DL:N1:CR:S1
        client.print("T"); client.print(TABLE_NUM);
        client.print(":DL:N"); client.print(DEVICE_NUM);
        client.print(":C"); client.print(color);
        client.print(":S"); client.println(state);
      }
    }
  }
}