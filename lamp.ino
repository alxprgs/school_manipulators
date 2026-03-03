#include <SPI.h>
#include <Ethernet.h>
#include <EthernetUDP.h>
#include <Dynamixel2Arduino.h>

// ---------- Настройки лампы (без изменений) ----------
const char* DEVICE_ID = "ID:T3:DL:N1";
const int TABLE_NUM = 3;
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

// ---------- Настройки Dynamixel ----------
#define DXL_SERIAL   Serial3          // используем Serial3 на Mega
#define DXL_DIR_PIN  -1                // пин направления (если RS485, укажите номер пина)
const uint8_t MOTOR_IDS[] = {1, 4, 2, 3, 5, 6}; // ID моторов согласно фото (001,004,002,003,005,006)
const int NUM_MOTORS = sizeof(MOTOR_IDS) / sizeof(MOTOR_IDS[0]);
const uint32_t DXL_BAUDRATE = 57600;   // стандартная скорость Dynamixel, может отличаться

Dynamixel2Arduino dxl(DXL_SERIAL, DXL_DIR_PIN);

// ---------- Прототипы функций моторов ----------
void initMotors();
void setMotorPosition(uint8_t id, uint16_t position);
bool isValidMotorID(uint8_t id);

// ---------- Setup ----------
void setup() {
  pinMode(PIN_R, OUTPUT); pinMode(PIN_Y, OUTPUT);
  pinMode(PIN_G, OUTPUT); pinMode(PIN_B, OUTPUT);
  Serial.begin(9600);

  // Инициализация Ethernet
  Ethernet.begin(mac);
  delay(1000);
  Udp.begin(LOCAL_PORT);
  Serial.print("UDP started on port ");
  Serial.println(LOCAL_PORT);

  // Инициализация Dynamixel
  dxl.begin(DXL_BAUDRATE);
  dxl.setPortProtocolVersion(2.0);      // Протокол 2.0
  initMotors();                          // Пинг и включение моторов

  sendRegistration();
  lastRegSend = millis();
}

// ---------- Функции лампы (без изменений) ----------
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

// ---------- Функции моторов ----------
void initMotors() {
  for (int i = 0; i < NUM_MOTORS; i++) {
    uint8_t id = MOTOR_IDS[i];
    if (dxl.ping(id)) {
      Serial.print("Motor ID ");
      Serial.print(id);
      Serial.println(" found. Enabling torque...");
      dxl.torqueOn(id);
      dxl.setOperatingMode(id, OP_POSITION); // Режим управления позицией
      // Можно задать другие параметры: скорость, ускорение и т.д.
    } else {
      Serial.print("Motor ID ");
      Serial.print(id);
      Serial.println(" NOT responding.");
    }
  }
}

bool isValidMotorID(uint8_t id) {
  for (int i = 0; i < NUM_MOTORS; i++) {
    if (MOTOR_IDS[i] == id) return true;
  }
  return false;
}

void setMotorPosition(uint8_t id, uint16_t position) {
  if (!isValidMotorID(id)) {
    Serial.print("Invalid motor ID: ");
    Serial.println(id);
    return;
  }
  // Ограничение позиции (0-4095 для 12-битных моделей)
  position = constrain(position, 0, 4095);
  dxl.setGoalPosition(id, position, UNIT_RAW);
  Serial.print("Set motor ");
  Serial.print(id);
  Serial.print(" to position ");
  Serial.println(position);
  // При желании можно отправить подтверждение на сервер, но в данном примере не требуется
}

// ---------- Основной цикл ----------
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

      // ----- Команды лампы (без изменений) -----
      if (cmd == "1111") {
        digitalWrite(PIN_R, HIGH); digitalWrite(PIN_Y, HIGH);
        digitalWrite(PIN_G, HIGH); digitalWrite(PIN_B, HIGH);
        sendFullStatus();
      }
      else if (cmd == "0000") {
        digitalWrite(PIN_R, LOW); digitalWrite(PIN_Y, LOW);
        digitalWrite(PIN_G, LOW); digitalWrite(PIN_B, LOW);
        sendFullStatus();
      }
      else if (cmd.length() == 2) {
        char color = cmd.charAt(0);
        int state = cmd.substring(1).toInt();
        setColor(color, state);
      }
      // ----- Команды моторов (новые) -----
      else if (cmd.startsWith("M")) {
        // Формат: M<ID>:<POSITION>  (например "M001:2048")
        int colonIdx = cmd.indexOf(':');
        if (colonIdx > 1) {
          String idStr = cmd.substring(1, colonIdx);
          String posStr = cmd.substring(colonIdx + 1);
          uint8_t id = (uint8_t)idStr.toInt();
          uint16_t pos = (uint16_t)posStr.toInt();
          setMotorPosition(id, pos);
        } else {
          Serial.println("Invalid motor command format");
        }
      }
    }
  }

  // Периодическая отправка статуса лампы (без изменений)
  if (millis() - lastStatusSend >= STATUS_INTERVAL) {
    sendFullStatus();
    lastStatusSend = millis();
  }
  if (millis() - lastRegSend >= REG_INTERVAL) {
    sendRegistration();
    lastRegSend = millis();
  }
}
