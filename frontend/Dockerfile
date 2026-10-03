FROM node:22-alpine

WORKDIR /srv/web

COPY package*.json ./
RUN npm ci

COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev"]

