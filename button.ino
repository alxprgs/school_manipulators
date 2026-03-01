#include <SPI.h>
#include <Ethernet.h>

// --- НАСТРОЙКИ УСТРОЙСТВА ---
const char* DEVICE_ID = "ID:T1:DB:N1"; 
const int TABLE_NUM = 1;
const int DEVICE_NUM = 1;
const int BUTTON_PIN = 22;

byte mac[] = { 0xDE, 0xAD, 0xBE, 0xEF, 0xFE, 0x01 }; // Уникальный для каждого модуля
IPAddress server(192, 168, 1, 100); // IP твоего сервера
EthernetClient client;

bool lastButtonState = HIGH;

void setup() {
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  Serial.begin(9600);
  
  if (Ethernet.begin(mac) == 0) {
    Serial.println("Failed to configure Ethernet using DHCP");
  }
  delay(1000);
  
  connectToServer();
}

void connectToServer() {
  if (client.connect(server, 8888)) {
    client.println(DEVICE_ID);
    Serial.println("Connected and Identified");
  }
}

void loop() {
  if (!client.connected()) {
    connectToServer();
  }

  // 1. Проверка нажатия (Отдача 1.1)
  bool currentState = digitalRead(BUTTON_PIN);
  if (currentState != lastButtonState) {
    delay(50); // Дебаунс
    if (digitalRead(BUTTON_PIN) == currentState) {
      lastButtonState = currentState;
      int status = (currentState == LOW) ? 1 : 0;
      // Формат T1:DB:N1:BS1
      client.print("T"); client.print(TABLE_NUM);
      client.print(":DB:N"); client.print(DEVICE_NUM);
      client.print(":BS"); client.println(status);
    }
  }

  // 2. Чтение команд от сервера (Получение 1.2)
  if (client.available()) {
    String command = client.readStringUntil('\n');
    command.trim();

    if (command == "CS:HS") {
      // Ответ на Heartbeat
      client.print("T"); client.print(TABLE_NUM);
      client.print(":DB:N"); client.print(DEVICE_NUM);
      client.println(":HS:OK");
    } 
    else if (command == "CS:BS") {
      // Ответ на запрос статуса
      int status = (digitalRead(BUTTON_PIN) == LOW) ? 1 : 0;
      client.print("T"); client.print(TABLE_NUM);
      client.print(":DB:N"); client.print(DEVICE_NUM);
      client.print(":BS:"); client.println(status);
    }
  }
}